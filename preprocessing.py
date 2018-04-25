from gym import Wrapper, ObservationWrapper, spaces
from collections import deque
import numpy as np
import cv2

"""
Observation processing.

Section 8 ("Experimental Setup") of the paper says:
"The Atari experiments used the same input preprocessing as
(Mnih et al., 2015) and an action repeat of 4."

'Mnih et al., 2015' is
'Human-level control through deep reinforcement learning', which says:

  - First, to encode a single frame we take the maximum value for each
    pixel colour value over the frame being encoded and the previous frame.
    This was necessary to remove flickering that is present in games where
    some objects appear only in even frames while other objects appear only
    in odd frames, an artefact caused by the limited number of sprites Atari
    2600 can display at once.
  - Second, we then extract the Y channel, also known as luminance,
    from the RGB frame and rescale it to 84 x 84.
  - The function phi from algorithm 1 described below applies this
    preprocessing to the m most recent frames and stacks them to produce the
    input to the Q-function, in which m = 4, although the algorithm is robust
    to different values of m (for example, 3 or 5)."

Also:

  Following previous approaches to playing Atari 2600 games, we also use a
  simple frame-skipping technique. More precisely, the agent sees and selects
  actions on every kth frame instead of every frame, and its last action is
  repeated on skipped frames. Because running the emulator forward for one
  step requires much less computation than having the agent select an action,
  this technique allows the agent to play roughly k times more games without
  significantly increasing the runtime. We use k = 4 for all games.
  
There's some ambiguity about what order to apply these steps in. I think the 
right order should be:

1. Max over subsequent frames
   So - observation 0: max. over frames 0 and 1
        observation 1: max. over frames 1 and 2
        etc.
        
2. Extract luminance and scale

3. Skip frames
   So - observation 0: max. over frames 0 and 1
        observation 1: max. over frames 4 and 5
        etc.
        
4. Stack frames
   So - frame stack 0: max. over frames 0 and 1
                       max. over frames 4 and 5
                       max. over frames 8 and 9
                       max. over frames 12 and 13
                       
        frame stack 2: max. over frames 4 and 5
                       max. over frames 8 and 9
                       max. over frames 12 and 13
                       max. over frames 16 and 17
                       
The main ambiguity is whether frame skipping or frame stacking should be done
first. Above we've assumed frame skipping should be done first. If we did
frame stacking first, we would only look at every 4th frame stack: giving:

- Frame stack 0: max. over frames 0 and 1
                 max. over frames 1 and 2
                 max. over frames 2 and 3
                 max. over frames 3 and 4
                 
- Frame stack 4: max. over frames 4 and 5
                 max. over frames 5 and 6
                 max. over frames 6 and 7
                 max. over frames 7 and 8
                 
Note that there's a big difference: frame skip then frame stack gives the 
agent much less temporal scope than frame stack then frame skip. In the 
former, the agent has access to 12 frames' worth of observations, whereas in 
the latter, only 4 frames' worth.

Empirically, also, frame skip then frame stack does perform better.
"""


def get_noop_action_index(env):
    action_meanings = env.unwrapped.get_action_meanings()
    try:
        noop_action_index = action_meanings.index('NOOP')
        return noop_action_index
    except ValueError:
        raise Exception("Unsure about environment's NOOP action")


class MaxWrapper(Wrapper):
    """
    Take maximum pixel values over pairs of frames.
    """

    def __init__(self, env):
        Wrapper.__init__(self, env)
        self.frame_pairs = deque(maxlen=2)

    def reset(self):
        obs = self.env.reset()
        self.frame_pairs.append(obs)

        # The first frame returned should be the maximum of frames 0 and 1.
        # We get frame 0 from env.reset(). For frame 1, we take a no-op action.
        noop_action_index = get_noop_action_index(self.env)
        obs, _, done, _ = self.env.step(noop_action_index)
        if done:
            raise Exception("Environment signalled done during initial frame "
                            "maxing")
        self.frame_pairs.append(obs)
        return np.max(self.frame_pairs, axis=0)

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.frame_pairs.append(obs)
        obs_maxed = np.max(self.frame_pairs, axis=0)
        return obs_maxed, reward, done, info


class ExtractLuminanceAndScaleWrapper(ObservationWrapper):
    """
    Convert observations from colour to grayscale, then scale to 84 x 84
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        # Important so that gym's play.py picks up the right resolution
        self.observation_space = spaces.Box(low=0, high=255,
                                            shape=(84, 84),
                                            dtype=np.uint8)

    def observation(self, obs):
        obs = cv2.cvtColor(obs, cv2.COLOR_RGB2GRAY)
        # Bilinear interpolation
        obs = cv2.resize(obs, (84, 84), interpolation=cv2.INTER_LINEAR)
        return obs


class FrameStackWrapper(Wrapper):
    """
    Stack the most recent 4 frames together.
    """

    def __init__(self, env):
        Wrapper.__init__(self, env)
        self.frame_stack = deque(maxlen=4)

    def reset(self):
        obs = self.env.reset()
        self.frame_stack.append(obs)
        # The first frame returned should be a stack of frames 0 through 3.
        # We get frame 0 from env.reset(). For the rest, we take no-op actions.
        noop_action_index = get_noop_action_index(self.env)
        for _ in range(3):
            obs, _, done, _ = self.env.step(noop_action_index)
            if done:
                raise Exception("Environment signalled done during initial "
                                "frame stack")
            self.frame_stack.append(obs)
        return np.array(self.frame_stack)

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.frame_stack.append(obs)
        return np.array(self.frame_stack), reward, done, info


class ConcatFrameStack(ObservationWrapper):
    """
    Concatenate a stack horizontally into one long frame (for debugging).
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


class NumberFrames(ObservationWrapper):
    """
    Draw number of frames since reset (for debugging).
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        self.frames_since_reset = 0

    def observation(self, obs):
        cv2.putText(obs,
                    str(self.frames_since_reset),
                    org=(0, 70),  # x, y position of bottom-left corner of text
                    fontFace=cv2.FONT_HERSHEY_PLAIN,
                    fontScale=2.0,
                    color=(255, 255, 255),
                    thickness=2)
        self.frames_since_reset += 1
        return obs


class FrameSkipWrapper(Wrapper):
    """
    Repeat the chosen action for 4 frames, only returning the last frame.
    """

    def reset(self):
        return self.env.reset()

    def step(self, action):
        for _ in range(4):
            obs, reward, done, info = self.env.step(action)
            if done:
                break
        return obs, reward, done, info


class NormalizeWrapper(ObservationWrapper):
    """
    Normalize observations to range [0, 1].
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(84, 84), dtype=np.float32)

    def observation(self, obs):
        return obs / 255.0


class PongFeaturesWrapper(ObservationWrapper):
    """
    Manually extract the Pong game area, setting paddles/ball to 1.0 and the
    background to 0.0.
    """

    def __init__(self, env):
        ObservationWrapper.__init__(self, env)
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(84, 84), dtype=np.float32)

    def observation(self, obs):
        obs = np.mean(obs, axis=2) / 255.0  # Convert to [0, 1] grayscale
        obs = obs[34:194]  # Extract game area
        obs = obs[::2, ::2]  # Downsample by a factor of 2
        obs = np.pad(obs, pad_width=2, mode='constant')  # Pad to 84x84
        obs[obs <= 0.4] = 0  # Erase background
        obs[obs > 0.4] = 1  # Set balls, paddles to 1
        return obs


def generic_preprocess(env):
    env = MaxWrapper(env)
    env = ExtractLuminanceAndScaleWrapper(env)
    env = NormalizeWrapper(env)
    env = FrameSkipWrapper(env)
    env = FrameStackWrapper(env)
    return env


def pong_preprocess(env):
    env = PongFeaturesWrapper(env)
    env = FrameSkipWrapper(env)
    env = FrameStackWrapper(env)
    return env
