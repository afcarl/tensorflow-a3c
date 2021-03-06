#!/usr/bin/env python3

import os
import os.path as osp
import time
from threading import Thread

import easy_tf_log
import gym
import tensorflow as tf

import utils
from debug_wrappers import NumberFrames, MonitorEnv
from network import Network, make_inference_network
from params import parse_args
from utils import SubProcessEnv
from worker import Worker

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '1'  # filter out INFO messages


def make_networks(n_workers, n_actions,
                  weight_inits, value_loss_coef, entropy_bonus,
                  max_grad_norm, optimizer, debug):
    # https://www.tensorflow.org/api_docs/python/tf/Graph notes that graph
    # construction isn't thread-safe. So we all do all graph construction
    # serially before starting the worker threads.

    # Create shared parameters
    with tf.variable_scope('global'):
        make_inference_network(n_actions=n_actions, weight_inits=weight_inits)

    # Create per-worker copies of shared parameters
    worker_networks = []
    for worker_n in range(n_workers):
        create_summary_ops = (worker_n == 0)
        worker_name = "worker_{}".format(worker_n)
        network = Network(scope=worker_name,
                          n_actions=n_actions,
                          entropy_bonus=entropy_bonus,
                          value_loss_coef=value_loss_coef,
                          weight_inits=weight_inits,
                          max_grad_norm=max_grad_norm,
                          optimizer=optimizer,
                          summaries=create_summary_ops,
                          debug=debug)
        worker_networks.append(network)
    return worker_networks


def make_workers(sess, envs, networks, n_workers, log_dir):
    print("Starting {} workers".format(n_workers))
    workers = []
    for worker_n in range(n_workers):
        worker_name = "worker_{}".format(worker_n)
        worker_log_dir = osp.join(log_dir, worker_name)
        w = Worker(sess=sess, env=envs[worker_n], network=networks[worker_n],
                   log_dir=worker_log_dir)
        workers.append(w)

    return workers


def make_lr(lr_args, step_counter):
    initial_lr = tf.constant(lr_args['initial'])
    if lr_args['schedule'] == 'constant':
        lr = initial_lr
    elif lr_args['schedule'] == 'linear':
        steps = tf.cast(step_counter, tf.float32)
        zero_by_steps = tf.cast(lr_args['zero_by_steps'], tf.float32)
        lr = initial_lr * (1 - steps / zero_by_steps)
        lr = tf.clip_by_value(lr,
                              clip_value_min=0.0,
                              clip_value_max=float('inf'))
    return lr


def make_optimizer(learning_rate):
    # From the paper, Section 4, Asynchronous RL Framework,
    # subsection Optimization:
    # "We investigated three different optimization algorithms in our
    #  asynchronous framework – SGD with momentum, RMSProp without shared
    #  statistics, and RMSProp with shared statistics.
    #  We used the standard non-centered RMSProp update..."
    # "A comparison on a subset of Atari 2600 games showed that a variant
    #  of RMSProp where statistics g are shared across threads is
    #  considerably more robust than the other two methods."
    #
    # TensorFlow's RMSPropOptimizer defaults to centered=False,
    # so we're good there.
    #
    # For shared statistics, we supply the same optimizer instance to all
    # workers. Couldn't they still end up using
    # different statistics somehow?
    # a) From the source, RMSPropOptimizer's gradient statistics variables
    #    are associated with the variables supplied to apply_gradients(),
    #    which happen to be the global set of variables shared between all
    #    threads variables (see multi_scope_train_op.py).
    # b) Empirically, no. See shared_statistics_test.py.
    #
    # In terms of hyperparameters:
    #
    # Learning rate: the paper actually runs a bunch of
    # different learning rates and presents results averaged over the
    # three best learning rates for each game. From the scatter plot of
    # performance for different learning rates, Figure 2, it looks like
    # 7e-4 is a safe bet which works across a variety of games.
    # TODO: 7e-4
    #
    # RMSprop hyperparameters: Section 8, Experimental Setup, says:
    # "All experiments used...RMSProp decay factor of α = 0.99."
    # There's no mention of the epsilon used. I see that OpenAI's
    # baselines implementation of A2C uses 1e-5 (https://git.io/vpCQt),
    # instead of TensorFlow's default of 1e-10. Remember, RMSprop divides
    # gradients by a factor based on recent gradient history. Epsilon is
    # added to that factor to prevent a division by zero. If epsilon is
    # too small, we'll get a very large update when the gradient history is
    # close to zero. So my speculation about why baselines uses a much
    # larger epsilon is: sometimes in RL the gradients can end up being
    # very small, and we want to limit the size of the update.

    optimizer = tf.train.RMSPropOptimizer(learning_rate=learning_rate,
                                          decay=0.99, epsilon=1e-5)
    return optimizer


def make_envs(env_id, preprocess_wrapper, max_n_noops, n_envs, seed, debug,
              log_dir):
    def make_make_env_fn(env_n):
        def thunk():
            env = gym.make(env_id)
            # We calculate the env seed like this so that changing the
            # global seed completely changes the whole set of env seeds.
            env_seed = seed * n_envs + env_n
            env.seed(env_seed)
            if debug:
                env = NumberFrames(env)
            env = preprocess_wrapper(env, max_n_noops)

            if env_n == 0:
                env_log_dir = osp.join(log_dir, "env_{}".format(env_n))
            else:
                env_log_dir = None
            env = MonitorEnv(env, "Env {}".format(env_n), log_dir=env_log_dir)

            return env

        return thunk

    # ALE /seems/ to be basically thread-safe, as long as environments aren't
    # created at the same time (see
    # https://github.com/mgbellemare/Arcade-Learning-Environment/issues/86).
    # So we create them serially.
    envs = []
    for env_n in range(n_envs):
        env = SubProcessEnv(make_make_env_fn(env_n))
        envs.append(env)
    return envs


def run_worker(worker, n_steps_to_run, steps_per_update, step_counter,
               update_counter):
    while int(step_counter) < n_steps_to_run:
        steps_ran = worker.run_update(steps_per_update)
        step_counter.increment(steps_ran)
        update_counter.increment(1)


def start_workers(n_steps, steps_per_update, step_counter, update_counter,
                  workers):
    worker_threads = []
    for worker in workers:
        thread = Thread(target=lambda:
        run_worker(worker=worker,
                   n_steps_to_run=n_steps,
                   steps_per_update=steps_per_update,
                   step_counter=step_counter,
                   update_counter=update_counter)
                        )
        thread.start()
        worker_threads.append(thread)
    return worker_threads


def main():
    args, lr_args, log_dir, preprocess_wrapper, ckpt_timer = parse_args()
    easy_tf_log.set_dir(log_dir)

    utils.set_random_seeds(args.seed)
    sess = tf.Session()

    envs = make_envs(args.env_id, preprocess_wrapper, args.max_n_noops,
                     args.n_workers, args.seed, args.debug, log_dir)

    step_counter = utils.GraphCounter(sess)
    update_counter = utils.GraphCounter(sess)
    lr = make_lr(lr_args, step_counter.value)
    optimizer = make_optimizer(lr)

    networks = make_networks(n_workers=args.n_workers,
                             n_actions=envs[0].action_space.n,
                             weight_inits=args.weight_inits,
                             value_loss_coef=args.value_loss_coef,
                             entropy_bonus=args.entropy_bonus,
                             max_grad_norm=args.max_grad_norm,
                             optimizer=optimizer,
                             debug=args.debug)

    # Why save_relative_paths=True?
    # So that the plain-text 'checkpoint' file written uses relative paths,
    # which seems to be needed in order to avoid confusing saver.restore()
    # when restoring from FloydHub runs.
    global_vars = tf.trainable_variables('global')
    saver = tf.train.Saver(global_vars, max_to_keep=1, save_relative_paths=True)
    checkpoint_dir = osp.join(log_dir, 'checkpoints')
    os.makedirs(checkpoint_dir)
    checkpoint_file = osp.join(checkpoint_dir, 'network.ckpt')

    if args.load_ckpt:
        print("Restoring from checkpoint '%s'..." % args.load_ckpt,
              end='', flush=True)
        saver.restore(sess, args.load_ckpt)
        print("done!")
    else:
        sess.run(tf.global_variables_initializer())

    workers = make_workers(sess=sess,
                           envs=envs,
                           networks=networks,
                           n_workers=args.n_workers,
                           log_dir=log_dir)

    worker_threads = start_workers(n_steps=args.n_steps,
                                   steps_per_update=args.steps_per_update,
                                   step_counter=step_counter,
                                   update_counter=update_counter,
                                   workers=workers)
    ckpt_timer.reset()
    step_rate = utils.RateMeasure()
    step_rate.reset(int(step_counter))
    while True:
        time.sleep(args.wake_interval_seconds)

        steps_per_second = step_rate.measure(int(step_counter))
        easy_tf_log.tflog('misc/steps_per_second', steps_per_second)
        easy_tf_log.tflog('misc/steps', int(step_counter))
        easy_tf_log.tflog('misc/updates', int(update_counter))
        easy_tf_log.tflog('misc/lr', sess.run(lr))

        alive = [t.is_alive() for t in worker_threads]

        if ckpt_timer.done() or not any(alive):
            saver.save(sess, checkpoint_file, int(step_counter))
            print("Checkpoint saved to '{}'".format(checkpoint_file))
            ckpt_timer.reset()

        if not any(alive):
            break

    for env in envs:
        env.close()


if __name__ == '__main__':
    main()
