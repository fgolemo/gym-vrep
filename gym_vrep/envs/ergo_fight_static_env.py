import os
import time
import gym
import numpy as np
from gym import spaces
import logging

from gym_vrep.envs.constants import JOINT_LIMITS, BALL_STATES, RANDOM_NOISE
from gym_vrep.envs.normalized_wrapper import NormalizedActWrapper, NormalizedObsWrapper
from vrepper.core import vrepper

logger = logging.getLogger(__name__)

REST_POS = [0, 0, 0, 0, 0, 0]
RANDOM_NOISE = [
    (-90, 90),
    (-30, 30),
    (-30, 30),
    (-45, 45),
    (-30, 30),
    (-30, 30)
]
INVULNERABILITY_AFTER_HIT = 3  # how many frames after a hit to reset


class ErgoFightStaticEnv(gym.Env):
    def __init__(self, headless=True):
        self.headless = headless

        self._startEnv(headless)

        self.metadata = {
            'render.modes': ['human', 'rgb_array']
        }

        joint_boxes = spaces.Box(low=-1, high=1, shape=6)

        # own_joints = spaces.Box(low=-1, high=1,
        #                         shape=(6 + 6 + 3))  # 6 joint pos, 6 joint vel, 3 tip corrdinates

        own_joints = spaces.Box(low=-1, high=1, shape=(6 + 6))  # 6 joint pos, 6 joint vel

        cam_image = spaces.Box(low=0, high=255, shape=(256, 256, 3))

        self.observation_space = spaces.Tuple((cam_image, own_joints))
        self.action_space = joint_boxes

        self.diffs = [JOINT_LIMITS[i][1] - JOINT_LIMITS[i][0] for i in range(6)]
        self.frames_after_hit = -1  # -1 means no recent hit, anything 0 or above means it's counting

    def _seed(self, seed=None):
        np.random.seed(seed)

    def _startEnv(self, headless):
        self.venv = vrepper(headless=headless)
        self.venv.start()
        current_dir = os.path.dirname(os.path.realpath(__file__))
        self.venv.load_scene(current_dir + '/../scenes/poppy_ergo_jr_fight_sword1.ttt')
        self.motors = ([], [])
        for robot_idx in range(2):
            for motor_idx in range(6):
                motor = self.venv.get_object_by_name('r{}m{}'.format(robot_idx+1, motor_idx + 1), is_joint=True)
                self.motors[robot_idx].append(motor)
        self.sword_collision = self.venv.get_collision_object("sword_hit")
        self.cam = self.venv.get_object_by_name('cam', is_joint=False).handle
        # self.tip = self.frames_after_hit

    def _restPos(self):
        self.done = False
        self.venv.stop_simulation()
        self.venv.start_simulation(is_sync=True)

        for i, m in enumerate(self.motors[0]):
            m.set_position_target(REST_POS[i])

        self.randomize()

        for _ in range(15): #TODO test if 15 frames is enough
            self.venv.step_blocking_simulation()

    def randomize(self):
        for i in range(6):
            new_pos = REST_POS[i] + np.random.randint(
                low=RANDOM_NOISE[i][0],
                high=RANDOM_NOISE[i][1],
                size=1)[0]
            self.motors[1][i].set_position_target(new_pos)

    def _reset(self):
        self._restPos()
        self._self_observe()
        self.frames_after_hit = -1 # this enables hits / disables invulnerability frame
        return self.observation

    def _getReward(self):
        # The only way of getting reward is by hitting and releasing, hitting and releasing.
        # Just touching and holding doesn't work.
        reward = 0
        if self.sword_collision.is_colliding() and self.frames_after_hit == -1:
            reward = 1
            self.frames_after_hit = 0

        # the following bit is for making sure the robot doen't just hit repeatedly
        # ...so the invulnerability countdown only start when the collision is released
        else:  # if it's not hitting anything right now
            if self.frames_after_hit >= 0:
                self.frames_after_hit += 1
            if self.frames_after_hit >= INVULNERABILITY_AFTER_HIT:
                self.frames_after_hit = -1

        return reward

    def _self_observe(self):
        pos = []
        vel = []
        for i, m in enumerate(self.motors[0]):
            pos.append(m.get_joint_angle())
            vel.append(m.get_joint_velocity()[0])

        pos = self._normalize(pos) # move pos into range [-1,1]

        joint_vel = np.hstack((pos, vel)).astype('float32')
        cam_image = self.venv.get_image(self.cam)
        self.observation =(cam_image, joint_vel)

    def _gotoPos(self, pos):
        for i, m in enumerate(self.motors[0]):
            m.set_position_target(pos[i])

    def _normalize(self, pos):
        out = []
        for i in range(6):
            shifted = (pos[i] - JOINT_LIMITS[i][0]) / self.diffs[i]  # now it's in [0,1]
            norm = shifted * 2 - 1
            out.append(norm)
        return out

    def _denormalize(self, actions):
        out = []
        for i in range(6):
            shifted = (actions[i] + 1) / 2  # now it's within [0,1]
            denorm = shifted * self.diffs[i] + JOINT_LIMITS[i][0]
            out.append(denorm)
        return out

    def _step(self, actions):
        actions = np.clip(actions, -1, 1)  # first make sure actions are normalized
        actions = self._denormalize(actions)  # then scale them to the actual joint angles

        # step
        self._gotoPos(actions)
        self.venv.step_blocking_simulation()

        # observe again
        self._self_observe()

        return self.observation, self._getReward(), self.done, {}

    def _close(self):
        self.venv.stop_simulation()
        self.venv.end()

    def _render(self, mode='human', close=False):
        # This intentionally does nothing and is only here for wrapper functions.
        # if you want graphical output, use the environments
        # "ErgoBallThrowAirtime-Graphical-Normalized-v0"
        # or
        # "ErgoBallThrowAirtime-Graphical-v0"
        # ... not the ones with "...-Headless-..."
        pass

if __name__ == '__main__':
    import gym_vrep

    env = gym.make("ErgoFightStatic-v0")

    for k in range(3):
        observation = env.reset()
        print("init done")
        time.sleep(2)
        for i in range(30):
            if i % 5 == 0:
                # action = env.action_space.sample() # this doesn't work
                action = np.random.uniform(low=-1.0, high=1.0, size=(6))
            observation, reward, done, info = env.step(action)
            print(action, observation[0].shape, observation[1], reward, done)
            print(".")

    env.close()

    print('simulation ended. leaving in 5 seconds...')
    time.sleep(2)