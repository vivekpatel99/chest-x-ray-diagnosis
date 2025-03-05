from typing import Any

import pandas as pd
import tensorflow as tf
from polars import Date


class ChestXRayPreprocessor:
    def __init__(self, config, labels:list|None=None) -> None:
        """
        Initializes the ChestXRayPreprocessor class with configuration settings.

        Args:
            config: Configuration object containing various settings for training and dataset directories.
            labels (list, optional): List of labels to use for classification. If not provided, defaults to 
                                    ['Atelectasis', 'Effusion', 'Infiltration', 'Mass', 'Nodule'].

        Attributes:
            batch_size (int): The batch size for training, derived from the config.
            dataset_len (int): The length of the dataset, initialized to 0.
            LABELS (list): List of labels for classification.
            TRAIN_CSV_LABELS (list): List of labels for the training CSV file.
            normalization_layer (tf.keras.layers.Normalization): Normalization layer for preprocessing images.
            data_augmentation (tf.keras.Sequential): Sequential model for data augmentation, including random 
                                                    rotation, translation, and zoom.
        """
        self.config = config
        self.batch_size:int = config.TRAIN.BATCH_SIZE
        self.dataset_len:int = 0 
        self.image_size:int = config.TRAIN.IMG_SIZE
        if labels:
            self.LABELS = labels
        else:
            self.LABELS = ['Atelectasis','Effusion','Infiltration', 'Mass','Nodule']

        self.TRAIN_CSV_LABELS = ['Image Index', 'Finding Labels']

        self.normalization_layer = tf.keras.layers.Normalization()
        self.data_augmentation = tf.keras.Sequential([
            tf.keras.layers.RandomRotation(0.10),
            tf.keras.layers.RandomTranslation(0.05, 0.05),
            tf.keras.layers.RandomZoom(0.1, 0.1)
        ])


    def load_image(self, image_name, label, is_training=True)-> tuple[tf.Tensor, tf.Tensor]:
        img_dir = self.config.DATASET_DIRS.TRAIN_IMAGES_DIR if is_training else self.config.DATASET_DIRS.TEST_IMAGE_DIR
        full_path = tf.strings.join([img_dir, '/', image_name])
        image = tf.io.read_file(full_path)
        image = tf.io.decode_png(image, channels=1)
        image = tf.image.resize(image, 
                                [self.image_size, self.image_size], 
                                preserve_aspect_ratio=True,  
                                antialias=True)

        label = tf.cast(label, tf.float32)
        return image, label

    def augment_image(self, image, label)-> tuple[tf.Tensor, tf.Tensor]:
        return self.data_augmentation(image), label

    def prepare_dataset(self, dataset, batch_size, is_training=True)-> tf.data.Dataset:
        if is_training:
            dataset = dataset.map(self.augment_image, num_parallel_calls=tf.data.AUTOTUNE)
         
        dataset = dataset.map(self.normalize_image, num_parallel_calls=tf.data.AUTOTUNE)
        dataset = dataset.batch(batch_size)
        return dataset.prefetch(buffer_size=tf.data.AUTOTUNE)

    def get_class_weights(self, labels_df)-> tuple[tf.Tensor, tf.Tensor]:
        N = labels_df.shape[0]
        positive_frequencies = (labels_df == 1).sum() / N
        negative_frequencies = (labels_df == 0).sum() / N
        pos_weights = negative_frequencies.values
        neg_weights = positive_frequencies.values
        return pos_weights, neg_weights

    def train_df_clean_up(self, train_df)-> tuple[pd.DataFrame, pd.DataFrame]:
        new_train_df = train_df[self.TRAIN_CSV_LABELS]
        train_categorical_labels_df = new_train_df[self.TRAIN_CSV_LABELS[1]].str.get_dummies(sep='|').astype('float32')
        train_images_df = new_train_df['Image Index'] 
        train_categorical_labels_df = train_categorical_labels_df[self.LABELS]
        return train_images_df, train_categorical_labels_df

    def normalize_image(self, image, label)-> tuple[tf.Tensor, tf.Tensor]:
        image = self.normalization_layer(image)
        return image, label

    def _normlization_layer_adapt(self, dataset_len:int, train_ds:tf.data.Dataset) -> None:
        # images_for_stats =  tf.concat([images for images, _ in train_ds.take(int(dataset_len *0.30))], axis=0) 
        images_for_stats =  tf.concat([images for images, _ in train_ds.as_numpy_iterator()], axis=0) 
        self.normalization_layer.adapt(images_for_stats)

    def get_preprocessed_datasets(self, batch_size:int|None=None) -> tuple[tf.data.Dataset, tf.data.Dataset, tf.data.Dataset, tf.Tensor, tf.Tensor]:
        train_df, valid_df, test_df = self._load_dataframes()
        train_images_df, train_categorical_labels_df  = self.train_df_clean_up(train_df)
        train_ds = tf.data.Dataset.from_tensor_slices((train_images_df.values, train_categorical_labels_df.values))

        valid_ds = tf.data.Dataset.from_tensor_slices((valid_df['Image'].values, valid_df[self.LABELS].values))
        test_ds = tf.data.Dataset.from_tensor_slices((test_df['Image'].values, test_df[self.LABELS].values))

        train_ds = train_ds.map(lambda x, y: self.load_image(x, y, True), num_parallel_calls=tf.data.AUTOTUNE)
        train_ds = train_ds.shuffle(buffer_size=len(train_df))
        self._normlization_layer_adapt(dataset_len=len(train_df),train_ds=train_ds)
        valid_ds = valid_ds.map(lambda x, y: self.load_image(x, y, False), num_parallel_calls=tf.data.AUTOTUNE)
        test_ds = test_ds.map(lambda x, y: self.load_image(x, y, False), num_parallel_calls=tf.data.AUTOTUNE)

        if not batch_size:
            batch_size = self.config.TRAIN.BATCH_SIZE

        train_ds = self.prepare_dataset(train_ds, batch_size, is_training=True)
        valid_ds = self.prepare_dataset(valid_ds, batch_size, is_training=False)
        test_ds = self.prepare_dataset(test_ds, batch_size, is_training=False)

        pos_weights, neg_weights = self.get_class_weights(train_categorical_labels_df)

        return train_ds, valid_ds, test_ds, pos_weights, neg_weights

    def _load_dataframes(self)-> list[pd.DataFrame]:
        # Load and preprocess your dataframes here
        # This is a placeholder implementation
        train_df = pd.read_csv(self.config.DATASET_DIRS.TRAIN_CSV)
        valid_df = pd.read_csv(self.config.DATASET_DIRS.VALID_CSV)
        test_df = pd.read_csv(self.config.DATASET_DIRS.TEST_CSV)
        
        return [train_df, valid_df, test_df]
