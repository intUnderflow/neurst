# Copyright 2020 ByteDance Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import math

import tensorflow as tf

from neurst.utils.activations import get_activation


class PrePostProcessingWrapper(tf.keras.layers.Layer):
    """ Custom prepost processing for transformer.

    The sequence is specified as a string which may contain the
    following characters:
      a: add previous_x
      n: apply normalization
      d: apply drop'out

    This class only defines the "n" - layer - "da" mode.
    """

    def __init__(self, layer, dropout_rate=0.1,
                 name="layer_prepostprocess"):
        """ Initializes.

        Args:
            layer: The layer.
            dropout_rate: The dropout rate.
            name: The name of this layer.
        """
        super(PrePostProcessingWrapper, self).__init__(name=name)
        self._dropout_rate = dropout_rate
        self._layer = layer
        self._norm_layer = None

    def get_config(self):
        return dict(
            dropout_rate=self._dropout_rate,
            name=self.name)

    def build(self, input_shape):
        """ Creates norm layer. """
        self._norm_layer = tf.keras.layers.LayerNormalization(
            epsilon=1e-6, dtype="float32", name="ln")
        super(PrePostProcessingWrapper, self).build(input_shape)

    def call(self, inputs, *args, **kwargs):
        """ call norm before applying layer
        and call dropout+residuatl after applying layer
        """
        is_training = kwargs["is_training"]
        # n
        y = self._norm_layer(inputs)
        # layer: self att / ffn
        y = self._layer(y, *args, **kwargs)
        # d
        if is_training:
            y = tf.nn.dropout(y, rate=self._dropout_rate)
        # a
        return inputs + y


class TransformerFFN(tf.keras.layers.Layer):
    """ Applies the position-wise feed-forward as described
    in https://arxiv.org/abs/1706.03762 """

    def __init__(self,
                 filter_size,
                 output_size,
                 dropout_rate,
                 activation="relu",
                 name="ffn"):
        """ Initializes Transformer FFN.

        Args:
            filter_size: The hidden size of the relu layer.
            output_size: The output size.
            dropout_rate: The dropout rate.
            activation: The activation of internal layer.
            name: The name of this layer.
        """
        super(TransformerFFN, self).__init__(name=name)
        self._dropout_rate = dropout_rate
        self._filter_size = filter_size
        self._output_size = output_size
        self._activation = activation
        self._activation_fn = get_activation(activation)
        self._conv1 = None
        self._conv2 = None

    def get_config(self):
        return dict(
            filter_size=self._filter_size,
            output_size=self._output_size,
            dropout_rate=self._dropout_rate,
            activation=self._activation,
            name=self.name)

    def build(self, input_shape):
        self._conv1 = tf.keras.layers.Dense(
            self._filter_size,
            activation=self._activation_fn,
            use_bias=True,
            name="dense1")
        self._conv2 = tf.keras.layers.Dense(
            self._output_size,
            activation=None,
            use_bias=True,
            name="dense2")
        super(TransformerFFN, self).build(input_shape)

    def call(self, inputs, is_training=False):
        """ Returns the output of TransformerFFN.

        Args:
            inputs: A tensor with shape [batch_size, length, num_units].
            is_training: A boolean scalar, whether in training mode or not.

        Returns:
            Output of the feedforward network.
            tensor with shape [batch_size, length, output_size]
        """
        output = self._conv1(inputs)
        if is_training:
            output = tf.nn.dropout(output, rate=self._dropout_rate)
        output = self._conv2(output)
        return output


class MultiHeadDenseLayer(tf.keras.layers.Layer):
    """ Auto splitting or combining heads for the linear transformation. """

    def __init__(self,
                 output_units,
                 num_heads,
                 kernel_initializer=None,
                 bias_initializer="zeros",
                 activation=None,
                 use_bias=True,
                 is_output_transform=False,
                 name="transform"):
        """ Initializes MultiHeadDenseLayer.

        Args:
            output_units: A int scalar or int list, indicating the transformed output units.
                It must be a int scalar when `is_output_transform` is True.
            num_heads: The head num.
            kernel_initializer: The initializer of kernel weight.
            bias_initializer: The initializer of bias.
            activation: A string or a callable function for activation.
            use_bias: A boolean, whether to add bias tensor.
            is_output_transform: A boolean, whether to use this layer for the output
                transformation in multi head attention.
            name: The name of the layer.
        """
        super(MultiHeadDenseLayer, self).__init__(name=name)
        self._output_units = output_units
        self._num_heads = num_heads
        self._kernel_initializer = kernel_initializer
        self._bias_initializer = bias_initializer
        self._use_bias = use_bias
        self._is_output_transform = is_output_transform
        self._activation = activation
        self._activation_fn = get_activation(activation)
        # compatible
        self._flatten_output_units = tf.nest.flatten(self._output_units)
        if is_output_transform:
            assert not tf.nest.is_nested(self._output_units)

    def get_config(self):
        return dict(
            output_units=self._output_units,
            num_heads=self._num_heads,
            kernel_initializer=self._kernel_initializer,
            bias_initializer=self._bias_initializer,
            activation=self._activation,
            use_bias=self._use_bias,
            is_output_transform=self._is_output_transform,
            name=self.name)

    def compat_kernel_shape(self, input_shape):
        """ Compatible kernel for variable storage. """
        if self._is_output_transform:
            return [input_shape[-1] * input_shape[-2], self._output_units]
        return [input_shape[-1], sum(self._flatten_output_units)]

    @property
    def kernel_shape(self):
        """ The kernel shape. """
        if self._is_output_transform:
            return [self._num_heads, -1, self._output_units]
        return [-1, sum(self._flatten_output_units)]

    @property
    def bias_shape(self):
        """ The bias shape. """
        return [sum(self._flatten_output_units)]

    def build(self, input_shape):
        """ Builds the layer. """
        self._kernel = self.add_weight(
            "kernel",
            shape=self.compat_kernel_shape(input_shape),
            initializer=self._kernel_initializer,
            trainable=True)
        self._bias = None
        if self._use_bias:
            self._bias = self.add_weight(
                "bias",
                shape=self.bias_shape,
                initializer=self._bias_initializer,
                trainable=True)
        super(MultiHeadDenseLayer, self).build(input_shape)

    def call(self, inputs):
        """ Implements ``call()`` for MultiHeadDenseLayer.

        Args:
            inputs: A float tensor of shape [batch_size, length, hidden_size]
                when output_projection is False, otherwise a float tensor of shape
                [batch_size, length, num_heads, num_units_per_head].

        Returns:
            The projected tensor with shape [batch_size, length, num_heads,
                num_units_per_head] per `self._output_units` when output_projection
                is False, otherwise [batch_size, length, output_units].
        """
        kernel = tf.keras.backend.reshape(self._kernel, self.kernel_shape)
        if self._is_output_transform:
            # a: batch
            # b: length
            # c: num heads
            # d: input units per head
            # e: num_output
            output = tf.einsum("abcd,cde->abe", inputs, kernel)
        else:
            # a: batch
            # b: length
            # c: input size
            # d: total output size
            output = tf.einsum("abc,cd->abd", inputs, kernel)
        if self._use_bias:
            output += self._bias

        if not self._is_output_transform:
            output = tf.split(
                output, self._flatten_output_units,
                axis=-1)
            output = tf.nest.map_structure(
                lambda x, num_units: tf.reshape(
                    x, tf.concat([tf.shape(x)[:-1],
                                  [self._num_heads, num_units // self._num_heads]], axis=0)),
                output, self._flatten_output_units)
        output = tf.nest.flatten(output)
        if self._activation_fn is not None:
            output = tf.nest.map_structure(
                self._activation_fn, output)
        return tf.nest.pack_sequence_as(self._output_units, output)


class PositionEmbeddingWrapper(tf.keras.layers.Layer):

    def __init__(self,
                 timing,
                 embedding_layer,
                 max_positions=512,
                 name="position_emb_wrapper"):
        """ Initializes the position embedding layer.

        Args:
            timing: The position embedding type. Now only 'sinusoids'
                and 'emb' are supported.
            embedding_layer: The embedding layer.
            max_positions: The maximum positions.
            name: The name of this layer.
        """
        super(PositionEmbeddingWrapper, self).__init__(name=name)
        self._timing = timing
        self._embedding_layer = embedding_layer
        self._embedding_dim = embedding_layer.embedding_dim
        self._max_positions = max_positions
        assert self._timing in [None, "sinusoids", "emb"], (
            "Unknown position embedding type: \"{}\"".format(timing))

    def get_config(self):
        return dict(
            timing=self._timing,
            max_positions=self._max_positions,
            embedding_dim=self._embedding_dim,
            name=self.name)

    def build(self, input_shape):
        if self._timing == "emb":
            self._position_emb_table = self.add_weight(
                "weights",
                shape=[self._max_positions, self._embedding_dim],
                initializer=tf.random_normal_initializer(
                    mean=0., stddev=self._embedding_dim ** -0.5),
                trainable=True)
        super(PositionEmbeddingWrapper, self).build(input_shape)

    @staticmethod
    def add_sinusoids_timing_signal(x, time, min_timescale=1.0, max_timescale=1.0e4):
        """Adds a bunch of sinusoids of different frequencies to a Tensor.

        Each channel of the input Tensor is incremented by a sinusoid of a different
        frequency and phase.

        This allows attention to learn to use absolute and relative positions.
        Timing signals should be added to some precursors of both the query and the
        memory inputs to attention.

        The use of relative position is possible because sin(x+y) and cos(x+y) can be
        experessed in terms of y, sin(x) and cos(x).

        In particular, we use a geometric sequence of timescales starting with
        min_timescale and ending with max_timescale.  The number of different
        timescales is equal to channels / 2. For each timescale, we
        generate the two sinusoidal signals sin(timestep/timescale) and
        cos(timestep/timescale).  All of these sinusoids are concatenated in
        the channels dimension.

        This function is originally copied from Google's Tensor2Tensor code
        and modified to hold the capability for add timing signal at the
        specific time.

        Args:
          x: a Tensor with shape [batch, length, channels]
          min_timescale: a float
          max_timescale: a float

        Returns: A Tensor the same shape as x.
        """
        dtype = x.dtype.base_dtype
        channels = x.get_shape().as_list()[-1]
        if x.get_shape().ndims == 3:  # [batch_size, timesteps, dim]
            length = tf.shape(x)[1]
            position = tf.cast(tf.range(length), dtype=dtype)
        elif x.get_shape().ndims == 2:  # [batch_size, dim]
            length = 1
            position = tf.cast(tf.range(time, time + 1), dtype=dtype)
        else:
            raise ValueError("need a Tensor with rank 2 or 3")
        num_timescales = channels // 2
        log_timescale_increment = (
            math.log(float(max_timescale) / float(min_timescale))
            / (tf.cast(num_timescales, dtype) - 1))
        inv_timescales = min_timescale * tf.exp(
            tf.cast(tf.range(num_timescales), dtype=dtype) * -log_timescale_increment)
        scaled_time = tf.expand_dims(position, 1) * tf.expand_dims(inv_timescales, 0)
        signal = tf.concat([tf.sin(scaled_time), tf.cos(scaled_time)], axis=1)
        signal = tf.pad(signal, [[0, 0], [0, tf.math.mod(channels, 2)]])
        if x.get_shape().ndims == 3:
            signal = tf.reshape(signal, [1, length, channels])
        else:
            signal = tf.reshape(signal, [1, channels])
        return x + signal

    def call(self, inputs, time=None, **kwargs):
        emb = self._embedding_layer(inputs, **kwargs)
        mode = kwargs.get("mode", "embedding")
        if self._timing is None or mode != "embedding":
            return emb
        assert emb.get_shape()[-1] == self._embedding_dim, (
            "The position embedding dimension should match the "
            "embedding dimension: {} vs. {}".format(
                self._embedding_dim, emb.get_shape()[-1]))
        x_ndims = emb.get_shape().ndims
        if x_ndims == 2 and time is None:
            raise ValueError("\"time\" should be provided when input x has 2-dims")
        if self._timing == "sinusoids":
            emb *= self._embedding_dim ** 0.5
            return self.add_sinusoids_timing_signal(
                x=emb, time=time)
        if self._timing == "emb":
            if x_ndims == 2:
                position = tf.convert_to_tensor(time, dtype=tf.int32)
            elif x_ndims == 3:
                position = tf.range(tf.shape(emb)[1])
            else:
                raise ValueError("need a Tensor with rank 2 or 3")
            position_emb = tf.gather(self._position_emb_table, position)
            return emb + tf.expand_dims(position_emb, axis=0)
