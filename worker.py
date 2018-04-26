from collections import deque

import gym
import numpy as np
from easy_tf_log import tflog

import preprocessing
import utils
from network import create_network
from train_ops import *

G = 0.99
N_ACTIONS = 3
ACTIONS = np.arange(N_ACTIONS) + 1
N_FRAMES_STACKED = 4
N_MAX_NOOPS = 30


class Worker:

    def __init__(self, sess, env_id, worker_n, seed, log_dir):
        utils.set_random_seeds(seed)

        env = gym.make(env_id)
        env.seed(seed)

        self.env = preprocessing.EnvWrapper(env,
                                            prepro2=preprocessing.prepro2,
                                            frameskip=4)

        self.sess = sess

        worker_scope = "worker_%d" % worker_n
        self.network = create_network(worker_scope)
        self.summary_writer = tf.summary.FileWriter(log_dir, flush_secs=1)
        self.scope = worker_scope

        policy_optimizer = tf.train.RMSPropOptimizer(learning_rate=0.0005,
                                                     decay=0.99, epsilon=1e-5)
        value_optimizer = tf.train.RMSPropOptimizer(learning_rate=0.0005,
                                                    decay=0.99, epsilon=1e-5)

        self.update_policy_gradients, self.apply_policy_gradients, \
        self.zero_policy_gradients, self.grad_bufs_policy, \
        grads_policy_norm = \
            create_train_ops(self.network.policy_loss,
                             policy_optimizer,
                             update_scope=worker_scope,
                             apply_scope='global')

        self.update_value_gradients, self.apply_value_gradients, \
        self.zero_value_gradients, self.grad_bufs_value, \
        grads_value_norm = \
            create_train_ops(self.network.value_loss,
                             value_optimizer,
                             update_scope=worker_scope,
                             apply_scope='global')

        tf.summary.scalar('value_loss',
                          self.network.value_loss)
        tf.summary.scalar('policy_entropy',
                          tf.reduce_mean(self.network.policy_entropy))
        tf.summary.scalar('grads_policy_norm', grads_policy_norm)
        tf.summary.scalar('grads_value_norm', grads_value_norm)
        self.summary_ops = tf.summary.merge_all()

        self.copy_ops = utils.create_copy_ops(from_scope='global',
                                              to_scope=self.scope)

        self.frame_stack = deque(maxlen=N_FRAMES_STACKED)
        self.reset_env()

        self.t_max = 10000
        self.steps = 0
        self.episode_rewards = []
        self.render = False
        self.episode_n = 1

        self.value_log = deque(maxlen=100)
        self.fig = None

    def reset_env(self):
        self.frame_stack.clear()
        self.env.reset()

        n_noops = np.random.randint(low=0, high=N_MAX_NOOPS + 1)
        print("%d no-ops..." % n_noops)
        for i in range(n_noops):
            o, _, _, _ = self.env.step(0)
            self.frame_stack.append(o)
        while len(self.frame_stack) < N_FRAMES_STACKED:
            print("One more...")
            o, _, _, _ = self.env.step(0)
            self.frame_stack.append(o)
        print("No-ops done")

    @staticmethod
    def log_rewards(episode_rewards):
        reward_sum = sum(episode_rewards)
        print("Reward sum was", reward_sum)
        tflog('episode_reward', reward_sum)

    def sync_network(self):
        self.sess.run(self.copy_ops)

    def value_graph(self):
        import matplotlib.pyplot as plt
        if self.fig is None:
            self.fig, self.ax = plt.subplots()
            self.fig.set_size_inches(2, 2)
            self.ax.set_xlim([0, 100])
            self.ax.set_ylim([0, 2.0])
            self.line, = self.ax.plot([], [])

            self.fig.show()
            self.fig.canvas.draw()
            self.bg = self.fig.canvas.copy_from_bbox(self.ax.bbox)

        self.fig.canvas.restore_region(self.bg)

        ydata = list(self.value_log)
        xdata = list(range(len(self.value_log)))
        self.line.set_data(xdata, ydata)

        self.ax.draw_artist(self.line)
        self.fig.canvas.update()
        self.fig.canvas.flush_events()

    def run_update(self):
        states = []
        actions = []
        rewards = []
        i = 0

        self.sess.run([self.zero_policy_gradients,
                       self.zero_value_gradients])
        self.sync_network()

        done = False
        while not done and i < self.t_max:
            s = np.moveaxis(self.frame_stack, source=0, destination=-1)
            feed_dict = {self.network.s: [s]}
            a_p = self.sess.run(self.network.a_softmax, feed_dict=feed_dict)[0]
            a = np.random.choice(ACTIONS, p=a_p)

            o, r, done, _ = self.env.step(a)

            if self.render:
                self.env.render()
                feed_dict = {self.network.s: [s]}
                v = self.sess.run(self.network.graph_v, feed_dict=feed_dict)[0]
                self.value_log.append(v)
                self.value_graph()

            # The state used to choose the action.
            # Not the current state. The previous state.
            states.append(np.copy(s))
            actions.append(a)
            rewards.append(r)

            self.frame_stack.append(o)
            self.episode_rewards.append(r)

            i += 1

        last_state = np.copy(self.frame_stack)

        if done:
            print("Episode %d finished" % self.episode_n)
            self.log_rewards(self.episode_rewards)
            self.episode_rewards = []
            self.episode_n += 1

        if done:
            returns = utils.rewards_to_discounted_returns(rewards, G)
        else:
            # If we're ending in a non-terminal state, in order to calculate
            # returns, we need to know the return of the final state.
            # We estimate this using the value network.
            s = np.moveaxis(last_state, source=0, destination=-1)
            feed_dict = {self.network.s: [s]}
            last_value = self.sess.run(self.network.graph_v,
                                       feed_dict=feed_dict)[0]
            rewards += [last_value]
            returns = utils.rewards_to_discounted_returns(rewards, G)
            returns = returns[:-1]  # Chop off last_value

        feed_dict = {self.network.s: states,
                     self.network.a: actions,
                     self.network.r: returns}
        summaries, _, _ = self.sess.run([self.summary_ops,
                                         self.update_policy_gradients,
                                         self.update_value_gradients],
                                        feed_dict)
        self.summary_writer.add_summary(summaries, self.steps)

        self.sess.run([self.apply_policy_gradients,
                       self.apply_value_gradients])
        self.sess.run([self.zero_policy_gradients,
                       self.zero_value_gradients])

        self.steps += 1

        return i, done
