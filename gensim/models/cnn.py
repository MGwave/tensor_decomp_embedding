import datetime
import tensorflow as tf
import numpy as np
import time
import os

from collections import defaultdict


class EmbeddingCNN(object):
    '''
    Input is a C x |V| bag-of-words embedding of the context.
    Starts with a |V| x d fully connected embedding layer (or multiple: TODO).
    The resulting C x d embedded context matrix is passed into a CNN with one convolutional and one max pooling layer.
    Then, we use a softmax layer to get a probability distribution over the output.

    The cost function is calculated via negative sampling.
    '''
    def __init__(
        self,
        vocab_model,
        embedding_size,
        filter_sizes,
        num_filters,
        context_size,  # = 2 * vocab_model.window
    ):
        self.vocab_model = vocab_model
        self.vocab = vocab_model.vocab

        #with tf.Graph().as_default():
        self.sess = tf.Session()
        with self.sess.as_default():
            with tf.device('/gpu:1'):
                self.input_x = tf.placeholder(tf.int32, [None, context_size], name='input_x')
                self.input_y = tf.placeholder(tf.int32, [None, 1], name='input_y') # Index of correct word. (list for minibatching)
                self.dropout_keep_prob = tf.placeholder(tf.float32, name='dropout_keep_prob')
                self.create_embedding_layer(embedding_size)
                self.create_conv_pooling_layer(embedding_size, filter_sizes, num_filters, context_size)
                self.create_fully_connected_layer_and_loss_fn(num_filters_total=num_filters * len(filter_sizes), vocab_model=vocab_model)

    def write_graph(self):
        tf.train.SummaryWriter('/tmp/tf_logs', graph=self.sess.graph)

    def create_embedding_layer(self, embedding_size):
        with tf.name_scope('embedding'):
            W = tf.Variable(
                # |V| x d embedding matrix
                tf.random_uniform([len(self.vocab), embedding_size], minval=-1, maxval=1),
                name='embedding_matrix'
            )
            self.word_embedding = W
            # Embed the input. The embedding lookup takes in a list of numbers (not one-hot vectors).
            self.embedded_chars = tf.nn.embedding_lookup(W, self.input_x)
            # embedded_chars_expanded is of shape [None (minibatch size), context_size, embedding_size, 1 (#channel maps)]
            self.embedded_chars_expanded = tf.expand_dims(self.embedded_chars, -1)

    def create_conv_pooling_layer(self, embedding_size, filter_sizes, num_filters, context_size):
        pooled_outputs = []
        for filter_size in filter_sizes:
            with tf.name_scope('conv-maxpool-{}'.format(filter_size)):
                filter_shape = [filter_size, embedding_size, 1, num_filters]  # TODO: understand the dimensionality. Why is the third size 1?
                W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
                b = tf.Variable(tf.constant(0.1, shape=[num_filters]), name='b')
                conv = tf.nn.conv2d(
                    input=self.embedded_chars_expanded,
                    filter=W,
                    strides=[1,1,1,1],
                    padding='VALID',
                    use_cudnn_on_gpu=True,
                    name='conv',
                )
                h = tf.nn.relu(tf.nn.bias_add(conv, b), name='relu')
                pooled = tf.nn.max_pool(
                    h,
                    ksize=[1, context_size - filter_size + 1, 1, 1],
                    strides=[1,1,1,1],
                    padding='VALID',
                    name='pooling',
                )
                pooled_outputs.append(pooled)
        num_filters_total = num_filters * len(filter_sizes)
        # concatenate the pooled outputs into a single tensor (by their dimension 3, which is all the different filter outputs. All others dims will be the same.)
        # so h_pool is of shape [batch_size, 1, 1, num_filters_total]
        h_pool = tf.concat(3, pooled_outputs)
        # -1 flattens into 1D. So h_pool_flat is of shape [batch_size, num_filters_total].
        self.h_pool_flat = tf.reshape(h_pool, [-1, num_filters_total], name='h_pool_flat')

    def create_fully_connected_layer_and_loss_fn(self, num_filters_total, vocab_model):
        with tf.name_scope('dropout'):
            self.h_drop = tf.nn.dropout(self.h_pool_flat, self.dropout_keep_prob)
        with tf.name_scope('output'):
            self.embedding2 = tf.Variable(
                tf.truncated_normal(
                    #shape=[num_filters_total, len(vocab_model.vocab)],
                    shape=[len(self.vocab), num_filters_total],
                    stddev=0.01
                ),
                name='W',
            )
            b = tf.Variable(
                tf.constant(0., shape=[len(self.vocab)]),
                name='b'
            )
            #self.scores = tf.matmul(self.h_drop, W) + b
            #self.predictions = tf.argmax(self.scores, 1, name='predictions')
        self.create_loss_fn(self.embedding2, b, vocab_model)

    def create_loss_fn(self, fc_W, fc_b, vocab_model):
        with tf.name_scope('loss'), tf.device('/cpu:0'): # neg. sampling not implemented on GPU yet
            losses = tf.nn.nce_loss(
                weights=fc_W,
                biases=fc_b,
                inputs=self.h_drop,
                labels=self.input_y,
                num_sampled=self.vocab_model.negative,
                num_classes=len(vocab_model.vocab),
            )
            self.loss = tf.reduce_mean(losses)
        with tf.name_scope('accuracy'), tf.device('/cpu:0'):
            self.accuracy = tf.Variable(0.0)

    def set_accuracy(self, *args, **kwargs):
        embedding = self.embedding2.eval(self.sess)
        self.vocab_model.syn0 = embedding
        if hasattr(self.vocab_model, 'syn0norm'):
            # We must delete the syn0norm of the vocab in order to compute accuracy.
            # Because if it already has a syn0norm, it will keep using that value and not use the new embedding.
            del self.vocab_model.syn0norm
        accuracy = self.vocab_model.accuracy('~/code/w2v_eval/questions-words.txt')
        correct = defaultdict(float)
        totals = defaultdict(float)
        for d in accuracy:
            if d['section'] == 'total':
                correct['total'] += len(d['correct'])
                totals['total'] += len(d['correct'])
                totals['total'] += len(d['incorrect'])
            elif d['section'].startswith('gram'):
                correct['syn'] += len(d['correct'])
                totals['syn'] += len(d['correct'])
                totals['syn'] += len(d['incorrect'])
            else:
                correct['sem'] += len(d['correct'])
                totals['sem'] += len(d['correct'])
                totals['sem'] += len(d['incorrect'])
        print('sem accuracy: {}/{} = {}'.format(correct['sem'], totals['sem'], correct['sem'] / max(1, totals['sem'])))
        print('syn accuracy: {}/{} = {}'.format(correct['syn'], totals['syn'], correct['syn'] / max(1, totals['syn'])))
        return self.accuracy.assign(correct['total'] / float(max(1, totals['total'])))

    def train_step(self, x_batch, y_batch, dropout_keep_prob=.5, print_every=100):
        if self.start_time is None:
            self.start_time = time.time()
        feed_dict = {
            self.input_x: x_batch,
            self.input_y: y_batch,
            self.dropout_keep_prob: dropout_keep_prob,
        }
        _, step, summaries, loss = self.sess.run(
            [
                self.train_op,
                self.global_step,
                self.loss_summary,
                self.loss,
            ],
            feed_dict=feed_dict
        )
        time_str = datetime.datetime.now().isoformat()
        if step % print_every == 0:
            print("{}: step {}, loss {:g}".format(time_str, step, loss))
            print("avg time per batch: {}".format((time.time() - self.start_time) / print_every))
            self.start_time = time.time()
        self.train_summary_writer.add_summary(summaries, step)

    def dev_step(self, x_batch, y_batch):
        feed_dict = {
            self.input_x: x_batch,
            self.input_y: y_batch,
            self.dropout_keep_prob: 1.0,
        }
        step, summaries, loss = self.sess.run(
            [
                self.global_step,
                self.loss_summary,
                self.loss,
            ],
            feed_dict=feed_dict
        )
        time_str = datetime.datetime.now().isoformat()
        print("(dev) {}: step {}, loss {:g}".format(time_str, step, loss))
        self.dev_summary_writer.add_summary(summaries, step)

    def train(self, batches):
        with self.sess.as_default(), tf.device('/cpu:0'):
            ######## Misc housekeeping ###########
            timestamp = str(datetime.datetime.now())
            out_dir = os.path.abspath(os.path.join(os.path.curdir, 'tf', timestamp))
            print('Writing summaries to {}.'.format(out_dir))

            self.loss_summary = tf.scalar_summary('loss', self.loss)
            self.acc_summary = tf.scalar_summary('accuracy', self.accuracy)
            self.train_summary_writer = tf.train.SummaryWriter(os.path.join(out_dir, 'summaries', 'train'), self.sess.graph)
            self.dev_summary_writer = tf.train.SummaryWriter(os.path.join(out_dir, 'summaries', 'dev'), self.sess.graph)

            checkpoint_dir = os.path.abspath(os.path.join(out_dir, 'checkpoints'))
            checkpoint_prefix = os.path.join(checkpoint_dir, 'model')

            if not os.path.exists(checkpoint_dir):
                os.makedirs(checkpoint_dir)
            self.saver = tf.train.Saver(tf.all_variables())
            ######## /Misc housekeeping ###########

            self.global_step = tf.Variable(0, name='global_step', trainable=False)

            optimizer = tf.train.AdamOptimizer(learning_rate=1e-3)
            grads_and_vars = optimizer.compute_gradients(self.loss)

        with tf.device('/gpu:1'):
            self.train_op = optimizer.apply_gradients(grads_and_vars, self.global_step)

            self.sess.run(tf.initialize_all_variables())
            # TODO: look into using pre-trained values for our first word embedding.

            self.word_index = 0
            self.sent_index = 0
            self.start_time = None
            for batch in batches:
                x_batch, y_batch = zip(*batch)
                y_batch = np.reshape(y_batch, (len(y_batch), 1))
                self.train_step(x_batch, y_batch)
                current_step = tf.train.global_step(self.sess, self.global_step)
                #if current_step % 500 == 1:
                #    print("\nEvaluation: ")
                #    self.dev_step(x_batch, y_batch)
                if current_step % 2500 == 0:
                    path = self.saver.save(self.sess, checkpoint_prefix, global_step=current_step)
                    print('Saved model checkpoint to {}'.format(path))
                    self.set_accuracy()
            path = self.saver.save(self.sess, checkpoint_prefix, global_step=tf.train.global_step(self.sess, self.global_step))
            print('Saved FINAL model checkpoint to {}'.format(path))
            self.set_accuracy()

