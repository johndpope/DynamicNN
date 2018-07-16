""" rbm: restricted Boltzmann machine """

import os
import time
import warnings
import numpy as np
import tensorflow as tf

from .ebm import EnergyBasedModel

modelname = 'RBM'

class RestrictedBoltzmannMachine(EnergyBasedModel):
    """ RBM class """

    def __init__(self,
                 m0,             # num of visible layer units
                 m1,             # num of hidden  layer units
                 batchsize=32,   # batchsize
                 lr=0.01,        # learning rate
                 wd_l2=0.0001,   # weight decay, L2 loss
                 path_log_dir=None,  # path to log folder
                 ):

        # set the attributes of RBM
        self.M = [m0, m1]
        self.batchsize = batchsize
        self.lr = lr
        self.wd_l2 = wd_l2
        self.path_log_dir = path_log_dir

        self.dict_params = {'b0': None, 'b1': None, 'w': None}
        self.graph = tf.Graph()      # initialize the tf computational graph
        self.tensors = dict()        # initial dict to store tensors

        self.init_dict_params()      # fill with default values
        self.init_tensors()          # initialize tensors
        # self.params_dict_to_tensor() # update tensors with self.dict_params

    """ ----- methods related to parameter transfer, loading and saving -----"""

    def init_dict_params(self, dict_params=None):
        """
        initialize self.dict_params with default values, update self.dict_params if dict_params is given
        :param dict_params: {name_of_variable: numpy_array_of_values}
        :return: None
        """

        if dict_params is None:
            dict_params = dict()

        m0, m1 = self.M             # network size
        default_std = 0.01

        dict_params_default = {
            'b0': np.random.normal(size=[m0])*default_std,
            'b1': np.random.normal(size=[m1])*default_std,
            'w' : np.random.normal(size=[m0, m1])*default_std/np.sqrt(m0)
        }

        for key in self.dict_params:
            self.dict_params[key] = dict_params[key] if key in dict_params else dict_params_default[key]

        return None

    def init_tensors(self):
        """
        initialize the tf tensors in graph, stored in self.tensors
        :return:           None
        """

        m0, m1 = self.M             # network size
        batchsize = self.batchsize  # batch size

        # create tensors
        with self.graph.as_default():
            # place holder
            x0_in = tf.placeholder(shape=[batchsize, m0], name='x0_in', dtype=tf.float32)

            # variables
            b0 = tf.Variable(self.dict_params['b0'], name='b0', dtype='float32')
            b1 = tf.Variable(self.dict_params['b1'], name='b1', dtype='float32')
            w  = tf.Variable(self.dict_params['w'],  name='w',  dtype='float32')

        # store to self.tensors
        for tensor_name in ['x0_in', 'b0', 'b1', 'w']:
            self.tensors[tensor_name] = locals()[tensor_name]

        return None

    def params_tensor_to_dict(self):
        """ update self.dict_params with variables from tf graph; has to be run in a session """

        for key in self.dict_params:
            self.dict_params[key] = self.tensors[key].eval()

        return self.dict_params

    def params_dict_to_tensor(self, dict_params=None):
        """ update variables in tf graph with self.dict_params; has to be run in a session """

        if dict_params is None:
            dict_params = self.dict_params

        keys_loaded = []
        for key in dict_params:
            obj_assign = tf.assign(self.tensors[key], dict_params[key])
            obj_assign.eval()
            keys_loaded.append(key)
        print('model paramter {} updated from file'.format(keys_loaded))

    def load_parameters(self, **kwargs):
        """
        load model parameters from a hdf5 (h5) or pickle (pkl) file to model tensors
        :param filepathname: the complete file path and name of the file to store,
            if not given, generate using filedir, filename, fileext, find_last
        :param filedir:      directory of file
        :param filename:     name of file
        :param fileext:      extension of file, has to be either '.h5' or '.pkl'
        :param find_last:    whether to find the most recent model based on timecode
        :return:
        """

        if ('filename' not in kwargs) or (kwargs['filename'] == ''):
            kwargs['filename'] = modelname

        # read parameters from file
        self.dict_params = self.read_parameters(**kwargs)
        # update tf tensor variables
        self.params_dict_to_tensor()

    def save_parameters(self, **kwargs):
        """
        save model parameters to a hdf5 (h5) or pickle (pkl) file
        :param dict_params:   dictional of parameters to save
        :param filepathname:  the complete file path and name of the file to store,
            if not given, generate using filedir, filename, fileext, autotimecode
        :param filedir:       directory of file
        :param filename:      name of file
        :param fileext:       extension of file, has to be either '.h5' or '.pkl'
        :param auto_timecode: whether automatically add datetime code to the end filename, default to True
        :return:
        """

        if ('filename' not in kwargs) or (kwargs['filename'] == ''):
            kwargs['filename'] = modelname

        # update dict_params with tensor variables
        self.params_tensor_to_dict()
        # save to file
        self.write_parameters(dict_params=self.dict_params, **kwargs)

    """ ----- methods for tf operations -----"""

    def cal_energy(self, x0, x1=None):
        """
        compute system energy

        :param x0: visible layer (bottom)
        :param x1: hidden layer (top)
        :return:
        """
        b0, b1, w = [self.tensors[key] for key in ['b0', 'b1', 'w']]
        with tf.name_scope('cal_energy'):
            if x1 is None:
                x1 = self.cal_p1_given_x0(x0)
            E_uni_x0 = -tf.reduce_sum(x0 * b0, axis=1)
            E_uni_x1 = -tf.reduce_sum(x1 * b1, axis=1)
            E_bin = - tf.reduce_sum(tf.reduce_sum(x0[:, :, None] * w[None, :, :], axis=1) * x1, axis=1)
            E_sum = E_uni_x0 + E_uni_x1 + E_bin
        return E_sum

    def sample_x(self, p):
        """ bernoulli sampling process, does not change the shape of input p """
        with tf.name_scope('bernoulli_sample'):
            sample_shape = p.shape
            x = tf.where(p > tf.random_uniform(sample_shape),
                         tf.ones(sample_shape), tf.zeros(sample_shape))
        return x

    def cal_p1_given_x0(self, x0, w=None, b=None):
        """ prop-up: update p1 using x0 """
        if w is None:
            w = self.tensors['w']
        if b is None:
            b = self.tensors['b1']
        with tf.name_scope('prop_up'):
            z = tf.reduce_sum(x0[:, :, None] * w[None, :, :], axis=1) + b[None, :]
            p = tf.sigmoid(z)
        return p

    def cal_p0_given_x1(self, x1, w=None, b=None):
        """ prop-up: update p0 using x1 """
        if w is None:
            w = self.tensors['w']
        if b is None:
            b = self.tensors['b0']
        with tf.name_scope('prop_down'):
            z = tf.reduce_sum(x1[:, None, :] * w[None, :, :], axis=2) + b[None, :]
            p = tf.sigmoid(z)
        return p

    def gibbs_dud(self, x1):
        """ gibbs sampling down-up-down """
        with tf.name_scope('gibbs_dud'):
            p0_sample = self.cal_p0_given_x1(x1)
            x0_sample = self.sample_x(p0_sample)
            p1_sample = self.cal_p1_given_x0(x0_sample)
            x1_sample = self.sample_x(p1_sample)

        return p0_sample, x0_sample, p1_sample, x1_sample

    def gibbs_udu(self, x0):
        """ gibbs sampling down-up-down """
        with tf.name_scope('gibbs_udu'):
            p1_sample = self.cal_p1_given_x0(x0)
            x1_sample = self.sample_x(p1_sample)
            p0_sample = self.cal_p0_given_x1(x1_sample)
            x0_sample = self.sample_x(p0_sample)

        return p0_sample, x0_sample, p1_sample, x1_sample

    def gibbs_sample(self, x0=None, x1=None, num_steps=1, direction='auto'):
        """
        Gibbs sampling of the RBM network for num_steps
        :param x0:  data, shape=[num_data, num_neurons_m0]
        :param x1:  data, shape=[num_data, num_neurons_m1]
        :param num_steps: number of steps to run the sampling process over the network
        :param direction: one of ['up', 'down', 'auto'].  default to 'auto', decided by the existance of x0 or x1
        :return:          p0_sample, x0_sample, p1_sample, x1_sample
        """
        assert (x0 is not None) or (x1 is not None)
        assert direction in ['up', 'down', 'auto']
        if direction == 'auto':
            if (x0 is not None) and (x1 is None):
                direction = 'up'
            elif (x0 is None) and (x1 is not None):
                direction = 'down'
            else:
                direction = 'up'

        if direction == 'up':
            gibbs_cycle = lambda p0, x0, p1, x1: self.gibbs_udu(x0)
        elif direction == 'down':
            gibbs_cycle = lambda p0, x0, p1, x1: self.gibbs_dud(x1)
        else:
            gibbs_cycle = lambda p0, x0, p1, x1: self.gibbs_udu(x0)

        with tf.name_scope('gibbs_sample'):
            p0x0p1x1 = gibbs_cycle(None, x0, None, x1)
            steps_remain = tf.constant(num_steps-1)
            loop_vars = steps_remain, p0x0p1x1
            cond = lambda steps_remain, p0x0p1x1: steps_remain > 0
            body = lambda steps_remain, p0x0p1x1: (steps_remain-1, gibbs_cycle(*p0x0p1x1))
            _, [p0_sample, x0_sample, p1_sample, x1_sample] = tf.while_loop(cond, body, loop_vars)

        return p0_sample, x0_sample, p1_sample, x1_sample

    def contrastive_divergence(self, x0):
        """ constrastive divergence step """

        with tf.name_scope('CD'):

            # empirical value, as positive term
            p1_empir = self.cal_p1_given_x0(x0)
            x1_empir = self.sample_x(p1_empir)

            # model's prediction, as negative term
            p0_model, x0_model, p1_model, x1_model = self.gibbs_dud(x1_empir)

            with tf.name_scope('stats_pos'):
                stats_pos_b0 = tf.reduce_mean(x0, axis=0)
                stats_pos_b1 = tf.reduce_mean(p1_empir, axis=0)
                stats_pos_w = tf.reduce_mean(x0[:, :, None] * p1_empir[:, None, :], axis=0)

            with tf.name_scope('stats_neg'):
                stats_neg_b0 = tf.reduce_mean(p0_model, axis=0)
                stats_neg_b1 = tf.reduce_mean(p1_model, axis=0)
                stats_neg_w = tf.reduce_mean(p0_model[:, :, None] * x1_empir[:, None, :], axis=0)

            with tf.name_scope('grad_update'):
                update_b0 = tf.assign_add(self.tensors['b0'], self.lr * (stats_pos_b0 - stats_neg_b0))
                update_b1 = tf.assign_add(self.tensors['b1'], self.lr * (stats_pos_b1 - stats_neg_b1))
                update_w  = tf.assign_add(self.tensors['w'], self.lr * (stats_pos_w - stats_neg_w))
                update_all = [update_b0, update_b1, update_w]

        return update_all

    """ ----- functions related creating computational graph -----"""
    def init_graph(self):
        """ clear entire graph and put back x0_in, b0, b1, w """

        tf.reset_default_graph()
        self.graph = tf.Graph()
        self.init_tensors()

    def tensorboard_include_graph(self):
        """ include graph to tensorboard visualization """

        # create tensorboard visualization of graph
        if self.path_log_dir is not None:
            if os.path.isdir(self.path_log_dir):
                with tf.summary.FileWriter(self.path_log_dir) as writer:
                    writer.add_graph(self.graph)
            elif self.path_log_dir is not None:
                warnings.warn('given path_log_dir {} does not exist'.format(self.path_log_dir))

    def create_training_graph(self):
        """ create training graph """

        with self.graph.as_default():

            # define computational graph
            x0_in = self.tensors['x0_in']
            cd = self.contrastive_divergence(x0=x0_in)
            energy = self.cal_energy(x0=x0_in)

            # add summery node
            with tf.name_scope('summary'):
                tf.summary.histogram('b0', self.tensors['b0'])
                tf.summary.histogram('b1', self.tensors['b1'])
                tf.summary.histogram('w', self.tensors['w'])
                merged_summary = tf.summary.merge_all()

        # include tenstors in model object
        for tensor_name in ['cd', 'energy', 'merged_summary']:
            self.tensors[tensor_name] = locals()[tensor_name]

        # add graph to tensorboard
        self.tensorboard_include_graph()

        return self.graph

    """ ----- functions related to perform training and inference -----"""

    def run_training(self):
        """ """
        pass