import json
import math
import os
import torch

import numpy as np
from torch.utils.data import Dataset

from text import text_to_sequence, _out_symbol_to_id
from utils.tools import pad_1D

def load_free_styleTags_embedding(free_styleTags, flaubert_model, flaubert_tokenizer, decrease_weight_with_order=True, default_styleTag_emb_size=1024):
    annotations = free_styleTags.split(';')
    individual_embeddings = []
    for annotation in annotations:
        words = annotation.split(',')
        for i, word in enumerate(words):
            print(word)

            # Decrease magnitude of embedding with order in the list
            if decrease_weight_with_order:
                decreasing_weight = math.exp(-0.1*i)
            else:
                decreasing_weight = 1

            word_embedding = load_FlauBERT_embedding_from_styleTag(word.lower(), flaubert_model, flaubert_tokenizer)
            individual_embeddings.append(decreasing_weight * word_embedding)
    
    if individual_embeddings:
        free_styleTags_embedding = np.mean(individual_embeddings, axis=0)
    else:
        free_styleTags_embedding = np.zeros(default_styleTag_emb_size)

    return free_styleTags_embedding

def load_FlauBERT_embedding_from_styleTag(styleTag, flaubert_model, flaubert_tokenizer):
    tokens = flaubert_tokenizer.tokenize(styleTag)
    token_ids = flaubert_tokenizer.encode(tokens) # same as flaubert_tokenizer.encode(styleTag)
    with torch.no_grad():
        last_layer = flaubert_model(torch.tensor([token_ids]))[0][0, 1:-1, :].detach().numpy()
    # Sum token embeddings into word embedding
    styleTag_embedding = np.sum(last_layer, axis=0)

    return styleTag_embedding

class TextDataset(Dataset):
    def __init__(self, filepath, preprocess_config, mode_batch=False, use_bert=False, flaubert=None, flaubert_tokenizer=None, styleTag_encoder_config=None):
        self.cleaners = preprocess_config["preprocessing"]["text"]["text_cleaners"]

        self.basename, self.speaker, self.text, self.raw_text, self.phon_align, self.emotion_label, self.style_tag = self.process_meta(
            filepath
        )

        if mode_batch:
            config_preprocess_path = preprocess_config["path"]["preprocessed_path_batch"]
        else:
            config_preprocess_path = preprocess_config["path"]["preprocessed_path"]

        with open(
            os.path.join(
                config_preprocess_path, "speakers.json"
            )
        ) as f:
            self.speaker_map = json.load(f)

        self.use_bert = use_bert
        self.flaubert = flaubert
        self.flaubert_tokenizer = flaubert_tokenizer

        if styleTag_encoder_config is not None:
            self.use_styleTag_encoder = styleTag_encoder_config["use_styleTag_encoder"]
            self.styleTag_input_dim = styleTag_encoder_config["input_bert_size"]
        else:
            self.use_styleTag_encoder = False
            self.styleTag_input_dim = 0

        self.nbr_gst_tokens = preprocess_config["preprocessing"]["nbr_gst_tokens"]
        self.styleTag_size = preprocess_config["preprocessing"]["styleTag_size"]

    def __len__(self):
        return len(self.text)

    def __getitem__(self, idx):
        basename = self.basename[idx]
        speaker = self.speaker[idx]
        speaker_id = self.speaker_map[speaker]
        raw_text = self.raw_text[idx]
        phone = np.array(text_to_sequence(self.text[idx], self.cleaners))

        if self.phon_align[idx]:
            phon_align = np.array([_out_symbol_to_id.get(s,-1) for s in self.phon_align[idx].split()])
        else:
            phon_align = -1*np.ones(len(phone))

        if self.use_styleTag_encoder:
            styleTag_embedding = load_free_styleTags_embedding(self.style_tag[idx], self.flaubert, self.flaubert_tokenizer, default_styleTag_emb_size=self.styleTag_size)
        else:
            styleTag_embedding = None
            
        if self.emotion_label[idx]:
            emotion_label = int(self.emotion_label[idx])
        else:
            emotion_label = self.nbr_gst_tokens-1

        return (basename, speaker_id, phone, raw_text, phon_align, emotion_label, styleTag_embedding)

    def process_meta(self, filename):
        with open(filename, "r", encoding="utf-8") as f:
            name = []
            speaker = []
            text = []
            raw_text = []
            phon_align = []
            emotion_label = []
            style_tag = []
            for line in f.readlines():
                nbr_columns = line.strip("\n").count('|') + 1
                if nbr_columns == 4:
                    n, s, t, r = line.strip("\n").split("|")
                    a = []
                    e = []
                    s_t = []
                elif nbr_columns == 5:
                    e = []
                    s_t = []
                    n, s, t, r, a = line.strip("\n").split("|")
                elif nbr_columns == 6:
                    n, s, t, r, a, style = line.strip("\n").split("|")
                    if style.isdigit():
                        e = style
                        s_t = []
                    else:
                        s_t = style
                        e = []
                name.append(n)
                speaker.append(s)
                text.append(t)
                raw_text.append(r)
                phon_align.append(a)
                emotion_label.append(e)
                style_tag.append(s_t)
            return name, speaker, text, raw_text, phon_align, emotion_label, style_tag

    def collate_fn(self, data):
        ids = [d[0] for d in data]
        speakers = np.array([d[1] for d in data])
        texts = [d[2] for d in data]
        raw_texts = [d[3] for d in data]
        text_lens = np.array([text.shape[0] for text in texts])
        phon_aligns = [d[4] for d in data]
        
        emotion_labels = []
        for d in data:
            emotion_weights = np.zeros(self.nbr_gst_tokens)
            emotion_weights[d[5]] = 1
            emotion_labels.append(emotion_weights)

        if self.use_styleTag_encoder:
            styleTag_embs = np.array([d[7] for d in data])
        else:
            styleTag_embs = None

        texts = pad_1D(texts)
        phon_aligns = pad_1D(phon_aligns, -1)
        # emotion_labels = np.expand_dims(np.array(emotion_labels), axis=1)
        emotion_labels = np.array(emotion_labels)

        return ids, raw_texts, speakers, texts, text_lens, max(text_lens), phon_aligns, emotion_labels, styleTag_embs

if __name__ == "__main__":
    # Test
    import torch
    import yaml
    from torch.utils.data import DataLoader
    from utils.tools import to_device

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    preprocess_config = yaml.load(
        open("./config/LJSpeech/preprocess.yaml", "r"), Loader=yaml.FullLoader
    )
    train_config = yaml.load(
        open("./config/LJSpeech/train.yaml", "r"), Loader=yaml.FullLoader
    )

    train_dataset = Dataset(
        "train.txt", preprocess_config, train_config, sort=True, drop_last=True
    )
    val_dataset = Dataset(
        "val.txt", preprocess_config, train_config, sort=False, drop_last=False
    )
    train_loader = DataLoader(
        train_dataset,
        batch_size=train_config["optimizer"]["batch_size"] * 4,
        shuffle=True,
        collate_fn=train_dataset.collate_fn,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=train_config["optimizer"]["batch_size"],
        shuffle=False,
        collate_fn=val_dataset.collate_fn,
    )

    n_batch = 0
    for batchs in train_loader:
        for batch in batchs:
            to_device(batch, device)
            n_batch += 1
    print(
        "Training set  with size {} is composed of {} batches.".format(
            len(train_dataset), n_batch
        )
    )

    n_batch = 0
    for batchs in val_loader:
        for batch in batchs:
            to_device(batch, device)
            n_batch += 1
    print(
        "Validation set  with size {} is composed of {} batches.".format(
            len(val_dataset), n_batch
        )
    )
