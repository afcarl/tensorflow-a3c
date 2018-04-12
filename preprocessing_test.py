#!/usr/bin/env python3

import unittest

import gym
from numpy.testing import assert_array_equal
from pylab import *

from preprocessing import MaxWrapper, FrameStackWrapper, FrameSkipWrapper, \
    ExtractLuminanceAndScaleWrapper, preprocess_wrap, ConcatFrameStack


class DummyEnv(gym.Env):
    """
    A super-simple environment which just paints a white dot starting at (10, 10)
    and moving 10 pixels right on every step.

    If draw_n_dots is true, also indicate the current step number by the
    number of dots in each column.
    """

    OBS_DIMS = (210, 160, 3)

    def __init__(self):
        self.n_steps = None
        self.draw_n_dots = False

    def get_action_meanings(self):
        return ['NOOP']

    def reset(self):
        self.n_steps = 0
        return self._get_obs()

    def _get_obs(self):
        self.n_steps += 1
        obs = np.zeros(self.OBS_DIMS, dtype=np.uint8)
        x = 10 * self.n_steps
        obs[10, x] = 255
        if self.draw_n_dots:
            for i in range(1, self.n_steps):
                obs[10 + i * 10, x] = 255
        return obs

    def step(self, action):
        obs = self._get_obs()
        reward = 0
        done = False
        info = None

        return obs, reward, done, info


class TestPreprocessing(unittest.TestCase):

    def test_max_wrapper(self):
        env = DummyEnv()
        env_wrapped = MaxWrapper(env)

        actual_obs = env_wrapped.reset()
        # We expect to see a frame which is the maximum of frames 0 and 1
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 10] = 255
        expected_obs[10, 20] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frames 1 and 2
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 20] = 255
        expected_obs[10, 30] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frames 2 and 3
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 30] = 255
        expected_obs[10, 40] = 255
        assert_array_equal(actual_obs, expected_obs)

        # If we reset, we should see frames 0 and 1 again
        actual_obs = env_wrapped.reset()
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 10] = 255
        expected_obs[10, 20] = 255
        assert_array_equal(actual_obs, expected_obs)

    def test_extract_luminance_and_scale_wrapper(self):
        env = DummyEnv()
        env_wrapped = ExtractLuminanceAndScaleWrapper(env)

        # We should only have one colour channel now (luminance), with a size
        # of 84 x 84
        obs = env_wrapped.reset()
        self.assertEqual(obs.shape, (84, 84))

        obs, _, _, _ = env_wrapped.step(0)
        self.assertEqual(obs.shape, (84, 84))

    def test_frame_stack_wrapper(self):
        env = DummyEnv()
        env_wrapped = FrameStackWrapper(env)

        actual_obs = env_wrapped.reset()
        # We expect to see a stack of frames 0 to 3
        expected_obs = np.zeros((4,) + DummyEnv.OBS_DIMS, dtype=np.uint8)
        for frame_n, x in enumerate([10, 20, 30, 40]):
            expected_obs[frame_n, 10, x] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frames 1 to 4
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros((4,) + DummyEnv.OBS_DIMS, dtype=np.uint8)
        for frame_n, x in enumerate([20, 30, 40, 50]):
            expected_obs[frame_n, 10, x] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frames 2 to 5
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros((4,) + DummyEnv.OBS_DIMS, dtype=np.uint8)
        for frame_n, x in enumerate([30, 40, 50, 60]):
            expected_obs[frame_n, 10, x] = 255
        assert_array_equal(actual_obs, expected_obs)

        # If we reset, we should see frames 0 to 3 again
        actual_obs = env_wrapped.reset()
        expected_obs = np.zeros((4,) + DummyEnv.OBS_DIMS, dtype=np.uint8)
        for frame_n, x in enumerate([10, 20, 30, 40]):
            expected_obs[frame_n, 10, x] = 255
        assert_array_equal(actual_obs, expected_obs)

    def test_frame_skip_wrapper(self):
        env = DummyEnv()
        env_wrapped = FrameSkipWrapper(env)

        actual_obs = env_wrapped.reset()
        # We expect to see frame 0
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 10] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frame 4
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 50] = 255
        assert_array_equal(actual_obs, expected_obs)

        # Then frame 8
        actual_obs, _, _, _ = env_wrapped.step(0)
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 90] = 255
        assert_array_equal(actual_obs, expected_obs)

        # If we reset, we should see frame 0 again
        actual_obs = env_wrapped.reset()
        expected_obs = np.zeros(DummyEnv.OBS_DIMS, dtype=np.uint8)
        expected_obs[10, 10] = 255
        assert_array_equal(actual_obs, expected_obs)

    def check_full_preprocessing(self):
        """
        Manual check of the full set of preprocessing steps.
        Not run as part of normal unit tests; run me with
          ./preprocessing_test.py TestPreprocessing.check_full_preprocessing
        """
        env = DummyEnv()
        env.draw_n_dots = True
        env_wrapped = preprocess_wrap(env)

        obs1 = env_wrapped.reset()
        obs2, _, _, _ = env_wrapped.step(0)
        obs3, _, _, _ = env_wrapped.step(0)
        obs4 = env_wrapped.reset()

        subplot(4, 1, 1)
        imshow(np.hstack(obs1), cmap='gray')
        subplot(4, 1, 2)
        imshow(np.hstack(obs2), cmap='gray')
        subplot(4, 1, 3)
        imshow(np.hstack(obs3), cmap='gray')
        subplot(4, 1, 4)
        imshow(np.hstack(obs4), cmap='gray')

        show()

    def play_pong(self):
        """
        Manual check of full set of preprocessing steps for Pong.
        Not run as port of normal unit tests; run me with
          ./preprocessing_test.py TestPreprocessing.play_pong
        """
        from gym.utils import play as gym_play
        env = gym.make('PongNoFrameskip-v4')

        env_wrapped = ConcatFrameStack(preprocess_wrap(env))
        gym_play.play(env_wrapped, fps=15, zoom=4)


if __name__ == '__main__':
    unittest.main()