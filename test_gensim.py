import os
import gensim
import pickle
import sys
import tensorflow as tf
import numpy as np
from collections import defaultdict
from gensim.models.word2vec import Text8Corpus
from gensim.models.word2vec import BrownCorpus
from gensim.corpora.wikicorpus import WikiCorpus


#brown_loc = '/home/eric/nltk_data/corpora/brown'
#wiki_loc = '/home/eric/Downloads/enwiki-latest-pages-articles.xml.bz2'
text9_loc = '/cluster/home/ebaile01/data/enwik9'
text8_loc = '/cluster/home/ebaile01/data/enwik8'

corpus = 'text8'

corpus_dict = {
    #'brown': (BrownCorpus(brown_loc, False), 10, 30000),
    #'wiki': (WikiCorpus(wiki_loc), 5, 30),
    'text9': (Text8Corpus(text9_loc), 1, 30000),
    'text8': (Text8Corpus(text8_loc), 1, 30000),
}

sentences, iters, max_vocab_size = corpus_dict[corpus]


def print_accuracy(model):
    accuracy = model.accuracy('~/code/w2v_eval/questions-words.txt')
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
    print('sem accuracy: {}/{} = {}'.format(correct['sem'], totals['sem'], correct['sem']/max(1,totals['sem'])))
    print('syn accuracy: {}/{} = {}'.format(correct['syn'], totals['syn'], correct['syn']/max(1,totals['syn'])))
    print('total accuracy: {}/{} = {}'.format(correct['total'], totals['total'], correct['total']/max(1,totals['total'])))


def get_model_with_vocab(fname=corpus+'vocab', load=False):
    model = gensim.models.Word2Vec(iter=iters, max_vocab_size=max_vocab_size, negative=128, size=100, subspace=1)
    if load:
        print('depickling model...')
        with open(fname, 'rb') as f:
            model = pickle.load(f)
    else:
        print('building vocab...')
        model.build_vocab(sentences)
        with open(fname, 'wb') as f:
            pickle.dump(model, f)
    print('finished building vocab. length of vocab: {}'.format(len(model.vocab)))
    return model


def evaluate_embedding(embedding):
    model = get_model_with_vocab(load=True)
    model.syn0 = embedding
    # We must delete the syn0norm of the vocab in order to compute accuracy.
    # Because if it already has a syn0norm, it will keep using that value and not use the new embedding.
    model.clear_sims()
    print_accuracy(model)


def list_vars_in_checkpoint(dirname):
    from tensorflow.contrib.framework.python.framework.checkpoint_utils import list_variables
    abspath = os.path.abspath(dirname)
    return list_variables(abspath)


def main():
    if '--load' in sys.argv:
        model = get_model_with_vocab(corpus+'vocab', load=True)
        embedding = tf.Variable(tf.random_uniform([len(model.vocab), 100]), name="embedding/embedding_matrix")
        embedding2 = tf.Variable(tf.random_uniform([len(model.vocab), 100]), name="fully_connected/W")
        saver = tf.train.Saver(write_version=tf.train.SaverDef.V2)
        with tf.Session() as sess:
            saver.restore(sess, 'tf/text8_subspace100/checkpoints/model-163478')
            print(list_vars_in_checkpoint('tf/text8_subspace100/checkpoints/model-163478'))
            #print(list_vars_in_checkpoint('tf/2017-01-01 12:14:59.907021/checkpoints/model-163478'))
            embedding = embedding.eval(sess)
            embedding2 = embedding2.eval(sess)

            print('evaluating...')
        evaluate_embedding(embedding)
        evaluate_embedding(embedding2)
        def save_sent_jpeg(sentence, fname):
            sentence = sentence.split()
            model.syn0 = embedding
            word_vocabs = [model.vocab[w] for w in sentence if w in model.vocab]
            word_indices = np.asarray([v.index for v in word_vocabs])
            matrix = np.asarray([embedding[i] for i in word_indices])
            matrix = np.expand_dims(matrix, axis=2)
            min_matrix = -np.min(matrix)
            matrix = np.add(min_matrix, matrix)
            matrix = np.multiply(128. / np.max(matrix), matrix)
            matrix = tf.cast(matrix, tf.uint8)
            image = tf.image.encode_jpeg(matrix, quality=100)
            with tf.Session() as sess:
                with open(fname, 'w') as f:
                    jpeg = sess.run(image)
                    f.write(jpeg)

        vectors = {}
        for word in model.vocab:
            word_vocab = model.vocab[word]
            word_vect = embedding[word_vocab.index]
            vect_list = ['{:.3f}'.format(x) for x in word_vect]
            vectors[word] = ' '.join(vect_list)
        with open('vectors_w2v.txt', 'w') as f:
            for word in vectors:
                if not word:
                    continue
                f.write(word.encode('utf-8') + ' ' + vectors[word] + '\n')
        sys.exit()

    else:
        if '--loadvocab' not in sys.argv:
            model = get_model_with_vocab()
        else:
            with open(corpus+'vocab', 'rb') as f:
                model = pickle.load(f)

        print('training...')
        model.train(sentences)
        print('finished training!')

        # model.save(corpus+'model')

    print("most similar to king - man + woman: {}".format(model.most_similar(
        positive=['king', 'woman'], negative=['man'],
        topn=5,
    )))
    print("most similar to king: {}".format(model.most_similar(
        positive=['king'],
        topn=5,
    )))

    print_accuracy(model)
    print('Corpus: {} ({})'.format(sentences, corpus))
    print('iters: {}'.format(iters))
    print('vocab len: {}'.format(len(model.vocab)))


if __name__ == '__main__':
    main()
