import tensorflow as tf
from tensorflow.python.keras.models import  Model
from tensorflow.python.keras.layers import Input, Dense, Dropout, Layer, LSTM, Embedding, Dot, Concatenate
from tensorflow.python.keras.models import Model
from tensorflow.python.keras.regularizers import l2
from tensorflow.python.keras.initializers import glorot_uniform, Zeros


class MeanAggregator(Layer):

    def __init__(self, units, input_dim, neigh_max, concat=True, dropout_rate=0.0, activation=tf.nn.relu, l2_reg=0,
                 use_bias=False,
                 seed=1024, **kwargs):
        super(MeanAggregator, self).__init__()
        self.units = units
        self.neigh_max = neigh_max
        self.concat = concat
        self.dropout_rate = dropout_rate
        self.l2_reg = l2_reg
        self.use_bias = use_bias
        self.activation = activation
        self.seed = seed
        self.input_dim = input_dim

    def build(self, input_shapes):

        self.neigh_weights = self.add_weight(shape=(self.input_dim, self.units),
                                             initializer=glorot_uniform(
                                                 seed=self.seed),
                                             regularizer=l2(self.l2_reg),
                                             name="neigh_weights")
        if self.use_bias:
            self.bias = self.add_weight(shape=(self.units), initializer=Zeros(),
                                        name='bias_weight')

        self.dropout = Dropout(self.dropout_rate)
        self.built = True

    def call(self, inputs, training=None):
        features, node, neighbours = inputs

        node_feat = tf.nn.embedding_lookup(features, node)
        neigh_feat = tf.nn.embedding_lookup(features, neighbours)

        node_feat = self.dropout(node_feat, training=training)
        neigh_feat = self.dropout(neigh_feat, training=training)

        concat_feat = tf.concat([neigh_feat, node_feat], axis=1)
        concat_mean = tf.reduce_mean(concat_feat, axis=1, keepdims=False)

        output = tf.matmul(concat_mean, self.neigh_weights)
        if self.use_bias:
            output += self.bias
        if self.activation:
            output = self.activation(output)

        # output = tf.nn.l2_normalize(output,dim=-1)
        output._uses_learning_phase = True

        return output

    def get_config(self):
        config = {'units': self.units,
                  'concat': self.concat,
                  'seed': self.seed
                  }

        base_config = super(MeanAggregator, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class PoolingAggregator(Layer):

    def __init__(self, units, input_dim, neigh_max, aggregator='meanpooling', concat=True,
                 dropout_rate=0.0,
                 activation=tf.nn.relu, l2_reg=0, use_bias=False,
                 seed=1024, ):
        super(PoolingAggregator, self).__init__()
        self.output_dim = units
        self.input_dim = input_dim
        self.concat = concat
        self.pooling = aggregator
        self.dropout_rate = dropout_rate
        self.l2_reg = l2_reg
        self.use_bias = use_bias
        self.activation = activation
        self.neigh_max = neigh_max
        self.seed = seed

        # if neigh_input_dim is None:

    def build(self, input_shapes):

        self.dense_layers = [Dense(
            self.input_dim, activation='relu', use_bias=True, kernel_regularizer=l2(self.l2_reg))]

        self.neigh_weights = self.add_weight(
            shape=(self.input_dim * 2, self.output_dim),
            initializer=glorot_uniform(
                seed=self.seed),
            regularizer=l2(self.l2_reg),

            name="neigh_weights")

        if self.use_bias:
            self.bias = self.add_weight(shape=(self.output_dim,),
                                        initializer=Zeros(),
                                        name='bias_weight')

        self.built = True

    def call(self, inputs, mask=None):

        features, node, neighbours = inputs

        node_feat = tf.nn.embedding_lookup(features, node)
        neigh_feat = tf.nn.embedding_lookup(features, neighbours)

        dims = tf.shape(neigh_feat)
        batch_size = dims[0]
        num_neighbors = dims[1]
        h_reshaped = tf.reshape(
            neigh_feat, (batch_size * num_neighbors, self.input_dim))

        for l in self.dense_layers:
            h_reshaped = l(h_reshaped)
        neigh_feat = tf.reshape(
            h_reshaped, (batch_size, num_neighbors, int(h_reshaped.shape[-1])))

        if self.pooling == "meanpooling":
            neigh_feat = tf.reduce_mean(neigh_feat, axis=1, keep_dims=False)
        else:
            neigh_feat = tf.reduce_max(neigh_feat, axis=1)

        output = tf.concat(
            [tf.squeeze(node_feat, axis=1), neigh_feat], axis=-1)

        output = tf.matmul(output, self.neigh_weights)
        if self.use_bias:
            output += self.bias
        if self.activation:
            output = self.activation(output)

        # output = tf.nn.l2_normalize(output, dim=-1)

        return output

    def get_config(self):
        config = {'output_dim': self.output_dim,
                  'concat': self.concat
                  }

        base_config = super(PoolingAggregator, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

def GraphSAGE_LC(feature_dim, neighbor_num, n_hidden, n_classes, use_bias=True, activation=tf.nn.relu,
              aggregator_type='mean', dropout_rate=0.0, l2_reg=0):
    features = Input(shape=(feature_dim,))
    node_input = Input(shape=(1,), dtype=tf.int32)
    neighbor_input = [Input(shape=(l,), dtype=tf.int32) for l in neighbor_num]

    if aggregator_type == 'mean':
        aggregator = MeanAggregator
    else:
        aggregator = PoolingAggregator

    h = features
    for i in range(0, len(neighbor_num)):
        if i > 0:
            feature_dim = n_hidden
        h = aggregator(units=n_hidden, input_dim=feature_dim, activation=activation, l2_reg=l2_reg, use_bias=use_bias,
                       dropout_rate=dropout_rate, neigh_max=neighbor_num[i], aggregator=aggregator_type)(
            [h, node_input, neighbor_input[i]])  #
    
    pred_probs = Dense(n_classes, activation='softmax')(h)

    label_input = Input(shape=(n_classes,),name='label_input') # n * num_classes * num_classes
    label_emb = Embedding(n_classes, 128, input_length=n_classes ,name='label_emb1')(label_input) # n * num_classes * wvdim
    # label_emb = Bidirectional(LSTM(hidden_size,return_sequences=True),merge_mode='ave')(label_emb) # (n,d)
    label_emb = Dense(n_hidden,activation='tanh',name='label_emb2')(label_emb) # n * num_classes * hidden_size
            
    # similarity part:
    doc_product = Dot(axes=(2,1))([label_emb,h]) # (num_classes,hidden_size) dot (hidden_size,1) --> (num_classes,1)
    label_sim_dict = Dense(n_classes,activation='softmax',name='label_sim_dict')(doc_product)

    # concat output:
    concat_output = Concatenate()([pred_probs, label_sim_dict])

    input_list = [features, node_input] + neighbor_input + [label_input]
    # compile；
    return Model(input_list, concat_output)