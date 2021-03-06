import cv2
import easy_tf_log
import numpy as np
from easy_tf_log import tflog
from gym import spaces
from gym.core import ObservationWrapper, Wrapper

"""
Wrappers for gym environments to help with debugging.
"""


class NumberFrames(ObservationWrapper):
    """
    Draw number of frames since reset.
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        self.frames_since_reset = None

    def reset(self):
        self.frames_since_reset = 0
        return self.observation(self.env.reset())

    def observation(self, obs):
        # Make sure the numbers are clear even if some other wrapper takes
        # maxes observations over pairs of time steps
        if self.frames_since_reset % 2 == 0:
            x = 0
        else:
            x = 70
        cv2.putText(obs,
                    str(self.frames_since_reset),
                    org=(x, 70),
                    fontFace=cv2.FONT_HERSHEY_PLAIN,
                    fontScale=2.0,
                    color=(255, 255, 255),
                    thickness=2)
        self.frames_since_reset += 1
        return obs


class EarlyReset(Wrapper):
    """
    Reset the environment after 100 steps.
    """

    def __init__(self, env):
        Wrapper.__init__(self, env)
        self.n_steps = None

    def reset(self):
        self.n_steps = 0
        return self.env.reset()

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.n_steps += 1
        if self.n_steps >= 100:
            done = True
        return obs, reward, done, info


class ConcatFrameStack(ObservationWrapper):
    """
    Concatenate a stack horizontally into one long frame.
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        # Important so that gym's play.py picks up the right resolution
        self.observation_space = spaces.Box(low=0, high=255,
                                            shape=(84, 4 * 84),
                                            dtype=np.uint8)

    def observation(self, obs):
        assert obs.shape[0] == 4
        return np.hstack(obs)


class MonitorEnv(Wrapper):
    """
    Log per-episode rewards and episode lengths.
    """

    def __init__(self, env, prefix="", log_dir=None):
        Wrapper.__init__(self, env)

        if prefix:
            self.log_prefix = prefix + ": "
        else:
            self.log_prefix = ""

        if log_dir is not None:
            easy_tf_log.set_dir(log_dir)

        self.episode_rewards = None
        self.episode_length_steps = None
        self.episode_n = -1
        self.episode_done = None
        self.log_dir = log_dir

    def reset(self):
        self.episode_rewards = []
        self.episode_length_steps = 0
        self.episode_n += 1
        self.episode_done = False
        return self.env.reset()

    def step(self, action):
        if self.episode_done:
            raise Exception("Attempted to call step() after episode done")

        obs, reward, done, info = self.env.step(action)

        self.episode_rewards.append(reward)
        self.episode_length_steps += 1
        if done:
            reward_sum = sum(self.episode_rewards)
            print("{}Episode {} finished; reward sum {}".format(
                self.log_prefix, self.episode_n, reward_sum))
            if self.log_dir is not None:
                tflog('rl/episode_reward_sum', reward_sum)
                tflog('rl/episode_length_steps', self.episode_length_steps)
            self.episode_done = True

        return obs, reward, done, info
