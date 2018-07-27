import tensorflow as tf
import argparse
from models import Simple, NASNET, Inception, GAP, YOLO
from config import config
from Batchizer import Batchizer
from tqdm import tqdm
from utils import *
from Logger import Logger
import numpy as np
from augmentor import Augmentor


def create_model(session, m_type, m_name, logger):
    if m_type == "simple":
        model = Simple(m_name, config, logger)
    elif m_type == "YOLO":
        model = YOLO(m_name, config, logger)
    elif m_type == 'GAP':
        model = GAP(m_name, config, logger)
    elif m_type == 'NAS':
        model = NASNET(m_name, config, logger)
    elif m_type == 'INC':
        model = Inception(m_name, config, logger)
    else:
        raise ValueError

    ckpt = tf.train.get_checkpoint_state(model.model_dir)
    if ckpt and tf.train.checkpoint_exists(ckpt.model_checkpoint_path):
        logger.log('Reloading model parameters..')
        model.restore(session, ckpt.model_checkpoint_path)

    else:
        logger.log('Created new model parameters..')
        session.run(tf.global_variables_initializer())

    return model


def print_predictions(result, logger):
    logger.log("########### Print  Predictions ################")
    logger.log("label: [\tx\t\t y\t\t w\t\t h\t\t \a")
    for r in result:
        y = r[0]
        pred = r[1]
        img_path = r[2]

        logger.log("Path: " + img_path)
        logger.log("truth: {0:2.4f} {1:2.4f} {2:2.4f}".format(y[0],
                                                              y[1],
                                                              y[2]))
        logger.log("pred : {0:2.4f} {1:2.4f} {2:2.4f}\n".format(pred[0],
                                                                pred[1],
                                                                pred[2]))


def main(model_type, model_name, logger):
    with tf.Graph().as_default() as g:
        with tf.Session() as sess:

            # Create a new model or reload existing checkpoint
            model = create_model(sess, model_type, model_name, logger)

            # Create a log writer object
            log_writer = tf.summary.FileWriter(model.model_dir, graph=sess.graph)

            valid_loss = []
            train_loss = []

            saver = tf.train.Saver(max_to_keep=3)
            best_saver = tf.train.Saver(max_to_keep=1)

            root_path = "data/"
            train_csv = "train_data.csv"
            valid_csv = "valid_data.csv"

            train_path = os.path.join(root_path, train_csv)
            valid_path = os.path.join(root_path, valid_csv)
            # initial batchizer
            train_batchizer = Batchizer(train_path, config["batch_size"])
            valid_batchizer = Batchizer(valid_path, config["batch_size"])
# TODO: move arguments to class initializer
            # init augmentor
            ag = Augmentor('noisy_videos/', config)
            train_batches = train_batchizer.batches(ag,
                                                    config["output_dim"],
                                                    num_c=config["image_channel"],
                                                    zero_mean=True)
            valid_batches = valid_batchizer.batches(ag,
                                                    config["output_dim"],
                                                    num_c=config["image_channel"],
                                                    zero_mean=True)

            # check if learning rate set correctly
            # assert int(config["total_steps"] / config["decay_step"]) == len(config["learning_rate"])

            while model.global_step.eval() < config["total_steps"]:

                lr = config["learning_rate"][int(model.global_step.eval() / config["decay_step"])]
                with tqdm(total=config["validate_every"], unit="batches") as t:
                    for x, y, _ in train_batches:
                        if x is None:
                            continue

                        batch_loss, summary = model.train(sess, x, y, config["keep_prob"], lr)
                        train_loss.append(batch_loss)

                        t.set_description_str("batch_loss:{0:2.8f}, ".format(batch_loss))
                        log_writer.add_summary(summary, model.global_step.eval())
                        t.update(1)

                        if model.global_step.eval() % config["validate_every"] == 0:
                            break

                valid_counter = 0
                pred_result = []
                with tqdm(total=config["validate_for"], unit="batches") as t:
                    for x, y, img in valid_batches:
                        if x is None:
                            continue

                        batch_loss, _, pred = model.eval(sess, x, y)
                        valid_loss.append(batch_loss)

                        t.set_description_str("batch_loss:{0:2.8f}".format(batch_loss))
                        valid_counter += 1

                        # select a random image from current batch and add it for visualization
                        # do it with a little chance! to reduce the size of output
                        if np.random.rand() > 0.95:
                            r = np.random.randint(0, high=len(x))
                            pred_result.append([y[r], pred[r], img[r]])

                        t.update(1)

                        if valid_counter == config["validate_for"]:
                            break

                print_predictions(pred_result, logger)
                train_mean_loss = np.mean(train_loss)
                valid_mean_loss = np.mean(valid_loss)
                logger.log(
                    'Step:{0:6}: avg train loss:{1:2.8f}, avg validation loss:{2:2.8f}'.format(model.global_step.eval(),
                                                                                               train_mean_loss,
                                                                                               valid_mean_loss))

                # save a checkpoint with the best loss value
                if valid_mean_loss < logger.best_loss:
                    logger.save_best_loss(valid_mean_loss)
                    best_path = os.path.join(model.model_dir, "best_loss/")
                    check_dir(best_path)
                    save_path = best_saver.save(sess, best_path, global_step=model.global_step)
                    logger.log("model saved with best loss {0} at {1}".format(valid_mean_loss,
                                                                              save_path))

                # save_every and validate_every should be dividable, otherwise this step will jump
                if model.global_step.eval() % config["save_every"] == 0:
                    save_path = saver.save(sess, model.model_dir, global_step=model.global_step)
                    logger.log("model saved at {}".format(save_path))
                summary = tf.Summary()
                summary.value.add(tag="train_loss", simple_value=train_mean_loss)
                summary.value.add(tag="valid_loss", simple_value=valid_mean_loss)

                log_writer.add_summary(summary, model.global_step.eval())
                train_loss = []
                valid_loss = []

            logger.log('Training is done.')


if __name__ == "__main__":
    class_ = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=class_)

    model_name = "Inception_test"
    model_type = "INC"
    model_comment = "Inception without l2"

    logger = Logger(model_type, model_name, model_comment, config, dir="models/")
    logger.log("Start training model...")
    main(model_type, model_name, logger)
