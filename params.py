import argparse
import os
import sys
import time
from os import path as osp

import preprocessing
from utils import get_git_rev, Timer


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("env_id")
    parser.add_argument("--n_steps", type=float, default=10e6)
    parser.add_argument("--n_workers", type=int, default=1)
    parser.add_argument("--ckpt_interval_seconds", type=int, default=300)
    parser.add_argument("--load_ckpt")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--render", action='store_true')
    parser.add_argument("--max_n_noops", type=int, default=30)
    parser.add_argument("--debug", action='store_true')
    parser.add_argument("--steps_per_update", type=int, default=5)
    parser.add_argument("--value_loss_coef", type=float, default=0.5)
    parser.add_argument("--max_grad_norm", type=float, default=0.5)
    parser.add_argument("--entropy_bonus", type=float, default=0.01)
    parser.add_argument("--weight_inits",
                        choices=['ortho', 'glorot'],
                        default='ortho')
    parser.add_argument("--initial_lr", type=float, default=5e-4)
    parser.add_argument("--lr_schedule",
                        choices=['constant', 'linear'],
                        default='constant')
    parser.add_argument("--lr_decay_to_zero_by_n_steps", type=float)
    parser.add_argument("--preprocessing",
                        choices=['generic', 'pong'],
                        default='generic')
    parser.add_argument("--wake_interval_seconds", type=int, default=60)

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--log_dir')
    seconds_since_epoch = str(int(time.time()))
    group.add_argument('--run_name',
                       default='test-run_{}'.format(seconds_since_epoch))

    args = parser.parse_args()

    lr_args = check_lr_args(args, parser)
    log_dir = get_log_dir(args)
    save_args(args, log_dir)

    if args.preprocessing == 'generic':
        preprocess_wrapper = preprocessing.generic_preprocess
    elif args.preprocessing == 'pong':
        preprocess_wrapper = preprocessing.pong_preprocess

    ckpt_timer = Timer(duration_seconds=args.ckpt_interval_seconds)

    args.n_steps = int(args.n_steps)
    if args.lr_decay_to_zero_by_n_steps is not None:
        args.lr_decay_to_zero_by_n_steps = \
            int(args.lr_decay_to_zero_by_n_steps)

    return args, lr_args, log_dir, preprocess_wrapper, ckpt_timer


def check_lr_args(args, parser):
    if (args.lr_schedule == 'linear' and
            args.lr_decay_to_zero_by_n_steps is None):
        parser.error("For --lr_schedule linear, please supply "
                     "--lr_decay_to_zero_by_n_steps")
    if args.lr_decay_to_zero_by_n_steps is not None:
        if args.lr_schedule == 'constant':
            parser.error("--lr_decay_to_zero_by_n_steps is only relevant for "
                         "--lr_schedule linear")
        if args.lr_decay_to_zero_by_n_steps < args.n_steps:
            parser.error("lr_decay_to_zero_by_n_steps should be at least "
                         "n_steps")
    lr_args = {'initial': args.initial_lr,
               'schedule': args.lr_schedule,
               'zero_by_steps': args.lr_decay_to_zero_by_n_steps}
    return lr_args


def get_log_dir(args):
    if args.log_dir:
        log_dir = args.log_dir
    else:
        git_rev = get_git_rev()
        run_name = args.run_name + '_' + git_rev
        log_dir = osp.join('runs', run_name)
        if osp.exists(log_dir):
            raise Exception("Log directory '%s' already exists" % log_dir)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def save_args(args, log_dir):
    with open(osp.join(log_dir, 'args.txt'), 'w') as args_file:
        args_file.write(' '.join(sys.argv) + '\n\n')
        args_file.write(str(args) + '\n')


DISCOUNT_FACTOR = 0.99
