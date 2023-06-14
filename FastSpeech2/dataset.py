import json
import math
import os

import numpy as np
from torch.utils.data import Dataset

from text import text_to_sequence, _out_symbol_to_id
from utils.tools import pad_1D, pad_2D, pad_2D_copy_length


class Dataset(Dataset):
    def __init__(
        self, filename, preprocess_config, train_config, sort=False, drop_last=False
    ):
        self.dataset_name = preprocess_config["dataset"]
        self.preprocessed_path = preprocess_config["path"]["preprocessed_path"]
        self.cleaners = preprocess_config["preprocessing"]["text"]["text_cleaners"]
        self.batch_size = train_config["optimizer"]["batch_size"]

        self.au_size = preprocess_config["preprocessing"]["au"]["n_units"]

        self.basename, self.speaker, self.text, self.raw_text, self.phon_align = self.process_meta(
            filename
        )
        # print(self.phon_align)
        with open(os.path.join(self.preprocessed_path, "speakers.json")) as f:
            self.speaker_map = json.load(f)
        self.sort = sort
        self.drop_last = drop_last

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

        mel_path = os.path.join(
            self.preprocessed_path,
            "mel",
            "{}-mel-{}.npy".format(speaker, basename),
        )
        mel = np.load(mel_path)
        pitch_path = os.path.join(
            self.preprocessed_path,
            "pitch",
            "{}-pitch-{}.npy".format(speaker, basename),
        )
        pitch = np.load(pitch_path)
        energy_path = os.path.join(
            self.preprocessed_path,
            "energy",
            "{}-energy-{}.npy".format(speaker, basename),
        )
        energy = np.load(energy_path)
        duration_path = os.path.join(
            self.preprocessed_path,
            "duration",
            "{}-duration-{}.npy".format(speaker, basename),
        )
        duration = np.load(duration_path)

        au_path = os.path.join(
            self.preprocessed_path,
            "au",
            "{}-au-{}.npy".format(speaker, basename),
        )
        if os.path.exists(au_path):
            au = np.load(au_path)
            # print('toto')
            # print(au.shape)
            # print(mel.shape)

            # resize au if needed (same size as mel)
            if au.shape[0] > mel.shape[0]:
                au = au[:mel.shape[0], :]
            elif au.shape[0] < mel.shape[0]:
                for _ in range(mel.shape[0] - au.shape[0]):
                    au = np.concatenate((au, [au[-1, :]]), axis=0)

            # print(au.shape)
            # print(mel.shape)

        else:
            au = np.empty((0, self.au_size))

        # print(au)

        sample = {
            "id": basename,
            "speaker": speaker_id,
            "text": phone,
            "raw_text": raw_text,
            "mel": mel,
            "pitch": pitch,
            "energy": energy,
            "duration": duration,
            "phon_align": phon_align,
            "au": au,
        }
        # print(sample)

        return sample

    def process_meta(self, filename):
        with open(
            os.path.join(self.preprocessed_path, filename), "r", encoding="utf-8"
        ) as f:
            name = []
            speaker = []
            text = []
            raw_text = []
            phon_align = []
            for line in f.readlines():
                nbr_columns = line.strip("\n").count('|') + 1
                if nbr_columns == 4:
                    n, s, t, r = line.strip("\n").split("|")
                    a = []
                elif nbr_columns == 5:
                    n, s, t, r, a = line.strip("\n").split("|")
                name.append(n)
                speaker.append(s)
                text.append(t)
                raw_text.append(r)
                phon_align.append(a)
            return name, speaker, text, raw_text, phon_align

    def reprocess(self, data, idxs):
        ids = [data[idx]["id"] for idx in idxs]
        speakers = [data[idx]["speaker"] for idx in idxs]
        texts = [data[idx]["text"] for idx in idxs]
        raw_texts = [data[idx]["raw_text"] for idx in idxs]
        mels = [data[idx]["mel"] for idx in idxs]
        pitches = [data[idx]["pitch"] for idx in idxs]
        energies = [data[idx]["energy"] for idx in idxs]
        durations = [data[idx]["duration"] for idx in idxs]
        phon_aligns = [data[idx]["phon_align"] for idx in idxs]
        aus = [data[idx]["au"] for idx in idxs]

        text_lens = np.array([text.shape[0] for text in texts])
        mel_lens = np.array([mel.shape[0] for mel in mels])
        au_lens = np.array([au.shape[0] for au in aus])

        speakers = np.array(speakers)
        texts = pad_1D(texts)
        mels = pad_2D(mels)
        pitches = pad_1D(pitches)
        energies = pad_1D(energies)
        durations = pad_1D(durations)
        phon_aligns = pad_1D(phon_aligns, -1)
        # print('avant')
        # print(len(aus))
        # print(len(aus[0]))
        aus = pad_2D_copy_length(aus, mels)
        # aus = pad_2D(aus)
        # print('apres')
        # print(len(aus))
        # print(len(aus[0]))
        # print(len(mels[0]))
        # print('lens au')
        # print(au_lens)
        # print('lens mel')
        # print(mel_lens)
        # print(aus)

        return (
            ids,
            raw_texts,
            speakers,
            texts,
            text_lens,
            max(text_lens),
            mels,
            mel_lens,
            max(mel_lens),
            pitches,
            energies,
            durations,
            phon_aligns,
            aus,
            au_lens,
            max(au_lens),
        )

    def collate_fn(self, data):
        data_size = len(data)

        if self.sort:
            len_arr = np.array([d["text"].shape[0] for d in data])
            idx_arr = np.argsort(-len_arr)
        else:
            idx_arr = np.arange(data_size)

        tail = idx_arr[len(idx_arr) - (len(idx_arr) % self.batch_size) :]
        idx_arr = idx_arr[: len(idx_arr) - (len(idx_arr) % self.batch_size)]
        idx_arr = idx_arr.reshape((-1, self.batch_size)).tolist()
        if not self.drop_last and len(tail) > 0:
            idx_arr += [tail.tolist()]

        output = list()
        for idx in idx_arr:
            output.append(self.reprocess(data, idx))

        return output


class TextDataset(Dataset):
    def __init__(self, filepath, preprocess_config, mode_batch=False):
        self.cleaners = preprocess_config["preprocessing"]["text"]["text_cleaners"]

        self.basename, self.speaker, self.text, self.raw_text, self.phon_align, self.emotion_label = self.process_meta(
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
            
        if self.emotion_label[idx]:
            emotion_label = int(self.emotion_label[idx])
        else:
            emotion_label = 13

        return (basename, speaker_id, phone, raw_text, phon_align, emotion_label)

    def process_meta(self, filename):
        with open(filename, "r", encoding="utf-8") as f:
            name = []
            speaker = []
            text = []
            raw_text = []
            phon_align = []
            emotion_label = []
            for line in f.readlines():
                nbr_columns = line.strip("\n").count('|') + 1
                if nbr_columns == 4:
                    n, s, t, r = line.strip("\n").split("|")
                    a = []
                    e = []
                elif nbr_columns == 5:
                    e = []
                    n, s, t, r, a = line.strip("\n").split("|")
                elif nbr_columns == 6:
                    n, s, t, r, a, e = line.strip("\n").split("|")
                name.append(n)
                speaker.append(s)
                text.append(t)
                raw_text.append(r)
                phon_align.append(a)
                emotion_label.append(e)
            return name, speaker, text, raw_text, phon_align, emotion_label

    def collate_fn(self, data):
        ids = [d[0] for d in data]
        speakers = np.array([d[1] for d in data])
        texts = [d[2] for d in data]
        raw_texts = [d[3] for d in data]
        text_lens = np.array([text.shape[0] for text in texts])
        phon_aligns = [d[4] for d in data]
        
        nbr_tokens = 14
        emotion_labels = []
        for d in data:
            emotion_weights = np.zeros(nbr_tokens)
            emotion_weights[d[5]] = 1
            emotion_labels.append(emotion_weights)

        texts = pad_1D(texts)
        phon_aligns = pad_1D(phon_aligns, -1)
        # emotion_labels = np.expand_dims(np.array(emotion_labels), axis=1)
        emotion_labels = np.array(emotion_labels)

        return ids, raw_texts, speakers, texts, text_lens, max(text_lens), phon_aligns, emotion_labels


if __name__ == "__main__":
    # Test
    import torch
    import yaml
    from torch.utils.data import DataLoader
    from utils.utils import to_device

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
