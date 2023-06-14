import os
import json
import copy
import math
from collections import OrderedDict
from regex import B
import copy

import torch
import torch.nn as nn
import torch.nn.init as init
import numpy as np
import torch.nn.functional as F
from scipy.io import loadmat

from utils.tools import get_mask_from_lengths, pad

from text import text_to_sequence, _all_pct, _find_pattern_indexes_in_batch

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device = torch.device("cpu")

def get_sinusoid_encoding_table(n_position, d_hid, padding_idx=None):
    """ Sinusoid position encoding table """

    def cal_angle(position, hid_idx):
        return position / np.power(10000, 2 * (hid_idx // 2) / d_hid)

    def get_posi_angle_vec(position):
        return [cal_angle(position, hid_j) for hid_j in range(d_hid)]

    sinusoid_table = np.array(
        [get_posi_angle_vec(pos_i) for pos_i in range(n_position)]
    )

    sinusoid_table[:, 0::2] = np.sin(sinusoid_table[:, 0::2])  # dim 2i
    sinusoid_table[:, 1::2] = np.cos(sinusoid_table[:, 1::2])  # dim 2i+1

    if padding_idx is not None:
        # zero vector for padding dimension
        sinusoid_table[padding_idx] = 0.0

    return torch.FloatTensor(sinusoid_table)

class ReferenceEncoder(nn.Module):
    '''
    inputs --- [N, Ty/r, n_mels*r]  mels
    outputs --- [N, ref_enc_gru_size]
    '''

    def __init__(self, preprocess_config, model_config):

        super().__init__()
        
        K = len(model_config["gst"]["conv_filters"])
        filters = [1] + model_config["gst"]["conv_filters"]

        convs = [nn.Conv2d(in_channels=filters[i],
                           out_channels=filters[i + 1],
                           kernel_size=model_config["gst"]["ref_enc_size"],
                           stride=model_config["gst"]["ref_enc_strides"],
                           padding=model_config["gst"]["ref_enc_pad"]) for i in range(K)]
        self.convs = nn.ModuleList(convs)
        self.bns = nn.ModuleList([nn.BatchNorm2d(num_features=model_config["gst"]["conv_filters"][i]) for i in range(K)])

        out_channels = self.calculate_channels(
                preprocess_config["preprocessing"]["mel"]["n_mel_channels"], 
                model_config["gst"]["ref_enc_size"][0], model_config["gst"]["ref_enc_strides"][0], 
                model_config["gst"]["ref_enc_pad"][0], K)
                
        self.gru = nn.GRU(input_size=model_config["gst"]["conv_filters"][-1] * out_channels,
                          hidden_size=model_config["gst"]["gru_hidden"],
                          batch_first=True)
                          
        self.n_mel_channels = preprocess_config["preprocessing"]["mel"]["n_mel_channels"]
        self.ref_enc_gru_size = model_config["gst"]["gru_hidden"]

    def forward(self, inputs, input_lengths=None):
        out = inputs.view(inputs.size(0), 1, -1, self.n_mel_channels)
        for conv, bn in zip(self.convs, self.bns):
            out = conv(out)
            out = bn(out)
            out = F.relu(out)

        out = out.transpose(1, 2)  # [N, Ty//2^K, 128, n_mels//2^K]
        N, T = out.size(0), out.size(1)
        out = out.contiguous().view(N, T, -1)  # [N, Ty//2^K, 128*n_mels//2^K]

        # ------- Memory effectivness (not tested) ----------
        if input_lengths is not None:
            input_lengths = torch.ceil(input_lengths.float() / 2 ** len(self.convs))
            input_lengths = input_lengths.cpu().numpy().astype(int)            
            out = nn.utils.rnn.pack_padded_sequence(
                        out, input_lengths, batch_first=True, enforce_sorted=False)
        # ------- END ----------
                        
        self.gru.flatten_parameters() # initialy commented

        _, out = self.gru(out)
        return out.squeeze(0)

    def calculate_channels(self, L, kernel_size, stride, pad, n_convs):
        for _ in range(n_convs):
            L = (L - kernel_size + 2 * pad) // stride + 1
        return L
        
class STL(nn.Module):
    '''
    inputs --- [N, E//2]
    '''

    def __init__(self, model_config):

        super().__init__()
        self.embed = nn.Parameter(torch.FloatTensor(model_config["gst"]["n_style_token"], model_config["gst"]["token_size"] // model_config["gst"]["attn_head"]))
        d_q = model_config["gst"]["gru_hidden"]
        d_k = model_config["gst"]["token_size"] // model_config["gst"]["attn_head"]
        # self.attention = MultiHeadAttention(model_config["gst"]["attn_head"], model_config["gst"]["gru_hidden"], d_k, d_k, dropout=model_config["gst"]["dropout"])
        # self.attention = MultiHeadAttention(query_dim=d_q, key_dim=d_k, num_units=hp.E, num_heads=hp.num_heads)
        self.attention = MultiHeadCrossAttention(
            query_dim=d_q, key_dim=d_k, num_units=model_config["gst"]["token_size"],
            num_heads=model_config["gst"]["attn_head"])
            
        init.normal_(self.embed, mean=0, std=0.5)

    def forward(self, inputs, target_scores=None):
        if target_scores is None:
            N = inputs.size(0)
            query = inputs.unsqueeze(1)  # [N, 1, E//2]
        else:
            N = target_scores.size(0)
            query = None
            
        keys = F.tanh(self.embed).unsqueeze(0).expand(N, -1, -1)  # [N, token_num, E // num_heads]
        style_embed, attention_scores, unnormalized_attention_scores = self.attention(query, keys, target_scores)

        return style_embed, attention_scores, unnormalized_attention_scores

class MultiHeadCrossAttention(nn.Module):
    '''
    input:
        query --- [N, T_q, query_dim]
        key --- [N, T_k, key_dim]
    output:
        out --- [N, T_q, num_units]
    '''
    def __init__(self, query_dim, key_dim, num_units, num_heads):
        super().__init__()
        self.num_units = num_units
        self.num_heads = num_heads
        self.key_dim = key_dim

        self.W_query = nn.Linear(in_features=query_dim, out_features=num_units, bias=False)
        self.W_key = nn.Linear(in_features=key_dim, out_features=num_units, bias=False)
        self.W_value = nn.Linear(in_features=key_dim, out_features=num_units, bias=False)

    def forward(self, query, key, target_scores=None):
        split_size = self.num_units // self.num_heads
        
        if target_scores is None:
            querys = self.W_query(query)  # [N, T_q, num_units]
            querys = torch.stack(torch.split(querys, split_size, dim=2), dim=0)  # [h, N, T_q, num_units/h]
            keys = self.W_key(key)  # [N, T_k, num_units]
            keys = torch.stack(torch.split(keys, split_size, dim=2), dim=0)  # [h, N, T_k, num_units/h]
        
        values = self.W_value(key)
        values = torch.stack(torch.split(values, split_size, dim=2), dim=0)  # [h, N, T_k, num_units/h]

        if target_scores is None:
            # score = softmax(QK^T / (d_k ** 0.5))
            unnormalized_scores = torch.matmul(querys, keys.transpose(2, 3))  # [h, N, T_q, T_k]
            #scores = torch.matmul(querys, keys.transpose(2, 3))  # [h, N, T_q, T_k]

            scores = unnormalized_scores.detach().clone()
            scores = scores / (self.key_dim ** 0.5)
            scores = F.softmax(scores, dim=3)

            unnormalized_scores = torch.cat(torch.split(unnormalized_scores, 1, dim=0), dim=3).squeeze(0).transpose(1, 2)  # [N, T_k*h=num_units, T_q]
        else:
            unnormalized_scores = None
            scores = target_scores.unsqueeze(0).unsqueeze(2)

        #print(values)
        #print(values.shape)
        # out = score * V
        out = torch.matmul(scores, values)  # [h, N, T_q, num_units/h]
        out = torch.cat(torch.split(out, 1, dim=0), dim=3).squeeze(0)  # [N, T_q, num_units]
        
        # scores reshape (when multiple heads, scores concatenate along dim 2, then transpose for cross entropy
        scores = torch.cat(torch.split(scores, 1, dim=0), dim=3).squeeze(0).transpose(1, 2)  # [N, T_k*h=num_units, T_q]
        
        return out, scores, unnormalized_scores
        
class GST(nn.Module):
    def __init__(self, preprocess_config, model_config):
        super().__init__()
        self.encoder = ReferenceEncoder(preprocess_config, model_config)
        self.stl = STL(model_config)

    def forward(self, inputs, input_lengths=None, target_scores=None):
        if target_scores is not None:
            enc_out = None
        else:
            enc_out = self.encoder(inputs, input_lengths=input_lengths)
        style_embed, attention_scores, unnormalized_attention_scores = self.stl(enc_out, target_scores)

        return style_embed, attention_scores, unnormalized_attention_scores
        
class LST(nn.Module):
    def __init__(self, model_config):
        super().__init__()
        
        self.embed = nn.Parameter(torch.FloatTensor(model_config["lst"]["n_style_token"], model_config["lst"]["token_size"] // model_config["lst"]["attn_head"]))

        self.add_gst = model_config["lst"]["add_gst"]
        self.use_positional_encoding = model_config["lst"]["positional_encoding"]["use_positional_encoding"]
        self.add_positional_encoding = model_config["lst"]["positional_encoding"]["add_positional_encoding"]

        self.d_q = model_config["transformer"]["encoder_hidden"]

        if not self.add_gst:
            self.d_q += model_config["gst"]["token_size"]

        if self.use_positional_encoding:
            n_position = model_config["max_seq_len"] + 1
            self.max_seq_len = model_config["max_seq_len"]
            if self.add_positional_encoding:
                self.positional_encoding_dim = self.d_q
            else:
                self.positional_encoding_dim = model_config["lst"]["positional_encoding"]["dim"]
                self.d_q += self.positional_encoding_dim
            
            # Init Positional Encoding Table
            self.position_enc = nn.Parameter(
                get_sinusoid_encoding_table(n_position, self.positional_encoding_dim).unsqueeze(0),
                requires_grad=False,
            )

        d_k = model_config["lst"]["token_size"] // model_config["lst"]["attn_head"]
        self.attention = MultiHeadCrossAttention(
            query_dim=self.d_q, key_dim=d_k, num_units=model_config["lst"]["token_size"],
            num_heads=model_config["lst"]["attn_head"])
            
        init.normal_(self.embed, mean=0, std=0.5)

        # Find IDs of all punctuation marks
        self._all_pct_indexes = text_to_sequence(_all_pct)

    def forward(self, inputs, positional_indexes):
        # local_style_emb, attention_scores = self.stl(enc_out, target_scores)
        
        N = inputs.size(0)
        max_len = inputs.shape[1]
        # query = inputs.unsqueeze(1)  # [N, L, E]

        # Positional Encoding
        if self.use_positional_encoding:
            if not self.training and max_len > self.max_seq_len:
                pos_enc = get_sinusoid_encoding_table(
                    max_len, self.d_q
                )[: max_len, :].unsqueeze(0).expand(N, -1, -1).to(
                    inputs.device
                )
            else:
                pos_enc = self.position_enc[
                    :, :max_len, :
                ].expand(N, -1, -1)

            # Scale positional embeddings according to target (words, phones...)
            pos_enc_by_scale = pos_enc.clone()
            for i_utt in range(0, N):
                pos_enc_by_scale[i_utt, :, :] = pos_enc_by_scale[i_utt, positional_indexes[i_utt, :]]
            if self.add_positional_encoding:
                inputs_cross_attention = inputs + pos_enc_by_scale
            else:
                inputs_cross_attention = torch.cat((inputs, pos_enc_by_scale), 2)
        
        keys = F.tanh(self.embed).unsqueeze(0).expand(N, -1, -1)  # [N, token_num, E // num_heads]
        style_embed, attention_scores, _ = self.attention(inputs_cross_attention, keys)

        return style_embed, attention_scores

    def compute_embeddings_by_word(self, output_by_phon, texts):
        # output_by_phon.shape = torch.Size([batch_size, max_length_input, dim_model])
        # texts = torch.Size([batch_size, max_length_input])
        # 1 in texts are spaces, 0 is the padding
        #output_by_word = output_by_phon.detach().clone()
        output_by_word = output_by_phon.clone()

        positional_indexes = torch.Tensor([]).to(device)

        for i_utt in range(texts.shape[0]):
            positional_indexes_by_utt = torch.zeros(texts.shape[1], dtype=int).to(device)
            indexes_pct = torch.tensor((), dtype=int).to(device)
            for i_pct in self._all_pct_indexes:
                indexes_current_pct = (texts[i_utt] == i_pct).nonzero(as_tuple=True)[0]
                indexes_pct = torch.cat((indexes_pct, indexes_current_pct))
            
            indexes_pct, _ = torch.sort(indexes_pct)

            boundaries = torch.tensor(([0]), dtype=int).to(device)
            previous_pct_index = 0
            for i_pct in indexes_pct:
                if i_pct != previous_pct_index+1 and i_pct != 0:
                    # New pseudo-word
                    boundaries = torch.cat((boundaries, torch.tensor([previous_pct_index+1, i_pct]).to(device)))
                    
                previous_pct_index = i_pct
            # Add first padding index
            boundaries = torch.cat((boundaries, torch.tensor([previous_pct_index+1]).to(device)))
            
            for i_interval in range(0, boundaries.shape[0]-1):
                output_by_word[i_utt][boundaries[i_interval]:boundaries[i_interval+1]][:] = torch.mean(output_by_word[i_utt][boundaries[i_interval]:boundaries[i_interval+1]][:], 0)
                positional_indexes_by_utt[boundaries[i_interval]:boundaries[i_interval+1]] = i_interval

            positional_indexes_by_utt[boundaries[-1]:] = i_interval+1
            positional_indexes = torch.cat((positional_indexes, positional_indexes_by_utt.unsqueeze(0)), 0)

        return output_by_word, positional_indexes.long()

class VarianceAdaptor(nn.Module):
    """Variance Adaptor"""

    def __init__(self, preprocess_config, model_config, mode_batch=False):
        super(VarianceAdaptor, self).__init__()
        self.duration_predictor = VariancePredictor(model_config)
        self.length_regulator = LengthRegulator()
        self.pitch_predictor = VariancePredictor(model_config)
        self.energy_predictor = VariancePredictor(model_config)

        self.pitch_feature_level = preprocess_config["preprocessing"]["pitch"][
            "feature"
        ]
        self.energy_feature_level = preprocess_config["preprocessing"]["energy"][
            "feature"
        ]
        self.pitch_normalization = preprocess_config["preprocessing"]["pitch"][
            "normalization"
        ]
        self.energy_normalization = preprocess_config["preprocessing"]["energy"][
            "normalization"
        ]
        assert self.pitch_feature_level in ["phoneme_level", "frame_level"]
        assert self.energy_feature_level in ["phoneme_level", "frame_level"]

        pitch_quantization = model_config["variance_embedding"]["pitch_quantization"]
        energy_quantization = model_config["variance_embedding"]["energy_quantization"]
        n_bins = model_config["variance_embedding"]["n_bins"]
        assert pitch_quantization in ["linear", "log"]
        assert energy_quantization in ["linear", "log"]

        if mode_batch:
            config_preprocessed_path = preprocess_config["path"]["preprocessed_path_batch"]
        else:
            config_preprocessed_path = preprocess_config["path"]["preprocessed_path"]

        with open(
            os.path.join(config_preprocessed_path, "stats.json")
            # os.path.join(config_preprocessed_path, "stats_by_speaker.json")
        ) as f:
            # stats_by_speaker = json.load(f)
            stats = json.load(f)
            pitch_min, pitch_max = stats["pitch"][:2]
            self.pitch_mean, self.pitch_std = stats["pitch"][2:4]
            energy_min, energy_max = stats["energy"][:2]
            self.energy_mean, self.energy_std = stats["energy"][2:4]

        if pitch_quantization == "log":
            self.pitch_bins = nn.Parameter(
                torch.exp(
                    torch.linspace(np.log(pitch_min), np.log(pitch_max), n_bins - 1)
                ),
                requires_grad=False,
            )
        else:
            self.pitch_bins = nn.Parameter(
                torch.linspace(pitch_min, pitch_max, n_bins - 1),
                requires_grad=False,
            )
        if energy_quantization == "log":
            self.energy_bins = nn.Parameter(
                torch.exp(
                    torch.linspace(np.log(energy_min), np.log(energy_max), n_bins - 1)
                ),
                requires_grad=False,
            )
        else:
            self.energy_bins = nn.Parameter(
                torch.linspace(energy_min, energy_max, n_bins - 1),
                requires_grad=False,
            )

        self.pitch_embedding = nn.Embedding(
            n_bins, model_config["transformer"]["encoder_hidden"]
        )
        self.energy_embedding = nn.Embedding(
            n_bins, model_config["transformer"]["encoder_hidden"]
        )

        self.use_variance_predictor = model_config["use_variance_predictor"]
        self.use_variance_embeddings = model_config["use_variance_embeddings"]

        self.cleaners = preprocess_config["preprocessing"]["text"]["text_cleaners"]
        self.maximum_phoneme_duration = model_config["maximum_phoneme_duration"]

        self.pause_bias_vector = model_config["bias_vector"]["pause"]
        self.liaison_bias_vector = model_config["bias_vector"]["liaison"]
        
        self.embedding_bias = EmbeddingBias(model_config)
        self.save_embeddings_by_layer = model_config["save_embeddings_by_layer"]

        self.detach_energy_prediction = model_config["variance_predictor"]["detach_energy_prediction"]

    def get_pitch_embedding(self, x, target, mask, control):
        prediction = self.pitch_predictor(x, mask)
        if target is not None:
            embedding = self.pitch_embedding(torch.bucketize(target, self.pitch_bins))
        else:
            # prediction = prediction * control
            if self.pitch_normalization:
                # prediction = prediction * (control + (control-1)*self.pitch_mean/(self.pitch_std*prediction))
                # prediction = prediction + control/self.pitch_std
                prediction = prediction + control/3.5701
            else:
                # prediction = prediction * control
                prediction = prediction + control

            embedding = self.pitch_embedding(
                torch.bucketize(prediction, self.pitch_bins)
            )
            
            batch_size = prediction.size(dim=0)

        return prediction, embedding

    def get_energy_embedding(self, x, target, mask, control):
        prediction = self.energy_predictor(x, mask)
        if target is not None:
            embedding = self.energy_embedding(torch.bucketize(target, self.energy_bins))
        else:
            # prediction = prediction * control
            if self.energy_normalization:
                # prediction = prediction * (control + (control-1)*self.energy_mean/(self.energy_std*prediction))
                # prediction = prediction + control/self.energy_std
                prediction = prediction + control/8.4094
            else:
                # prediction = prediction * control
                prediction = prediction + control
            embedding = self.energy_embedding(
                torch.bucketize(prediction, self.energy_bins)
            )
        return prediction, embedding

    def forward(
        self,
        x,
        src_mask,
        mel_mask=None,
        max_len=None,
        pitch_target=None,
        energy_target=None,
        duration_target=None,
        p_control=0.0,
        e_control=0.0,
        d_control=1.0,
        control_bias_array=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ):

        log_duration_prediction = self.duration_predictor(x, src_mask)

        x_au = x.clone() # for visual prediction

        if self.pitch_feature_level == "phoneme_level":
            if self.use_variance_predictor["pitch"]:
                pitch_prediction, pitch_embedding = self.get_pitch_embedding(
                    x, pitch_target, src_mask, p_control
                )
                if self.use_variance_embeddings["pitch"] and not self.detach_energy_prediction:
                    x = x + pitch_embedding
            else:
                pitch_prediction = None
                
            if not self.training and not self.detach_energy_prediction:
                # Add Embedding Bias layer 8
                x = self.embedding_bias.layer_control(x, control_bias_array, 8)

        if self.save_embeddings_by_layer and not self.training:
            output_by_layer = x.unsqueeze(0)
        else:
            output_by_layer = None

        if self.energy_feature_level == "phoneme_level":
            if self.use_variance_predictor["energy"]:
                energy_prediction, energy_embedding = self.get_energy_embedding(
                    x, energy_target, src_mask, e_control
                )
                if self.use_variance_embeddings["energy"] and not self.detach_energy_prediction:
                    x = x + energy_embedding
            else:
                energy_prediction = None
                
            if not self.training and not self.detach_energy_prediction:
                # Add Embedding Bias layer 9
                x = self.embedding_bias.layer_control(x, control_bias_array, 9)
                
        if self.detach_energy_prediction:
            if self.pitch_feature_level == "phoneme_level" and self.use_variance_embeddings["pitch"]:
                x = x + pitch_embedding

            if self.energy_feature_level == "phoneme_level" and self.use_variance_embeddings["energy"]:
                x = x + energy_embedding

        if self.save_embeddings_by_layer and not self.training:
            output_by_layer = torch.cat((output_by_layer, x.unsqueeze(0)), 0)

        if duration_target is not None:
            if self.maximum_phoneme_duration["limit"]: # impose max phon duration
                duration_threshold = self.maximum_phoneme_duration["threshold"]
                duration_target[duration_target>duration_threshold] = duration_threshold

            x, mel_len = self.length_regulator(x, duration_target, max_len)
            x_au, _ = self.length_regulator(x_au, duration_target, max_len)
            duration_rounded = duration_target
        else:
            # duration_rounded = torch.clamp(
            #     (torch.round(torch.exp(log_duration_prediction) - 1) * d_control),
            #     min=0,
            # )

            predicted_duration = (torch.exp(log_duration_prediction) - 1) * d_control
            predicted_duration_compensated = predicted_duration

            for utt_in_batch in range(x.size()[0]):
                residual = 0.0
                for index_phon in range(x.size()[1]):
                    dur_phon = predicted_duration[utt_in_batch][index_phon]
                    dur_phon_rounded = torch.round(dur_phon + residual)
                    residual += dur_phon - dur_phon_rounded
                    predicted_duration_compensated[utt_in_batch][index_phon] = dur_phon_rounded

            # Add residual to compensate for round
            duration_rounded = torch.clamp(
                predicted_duration_compensated,
                min=0,
            )

            x, mel_len = self.length_regulator(x, duration_rounded, max_len)
            x_au, _ = self.length_regulator(x_au, duration_rounded, max_len)
            mel_mask = get_mask_from_lengths(mel_len)

        if self.pitch_feature_level == "frame_level":
            if self.use_variance_predictor["pitch"]:
                pitch_prediction, pitch_embedding = self.get_pitch_embedding(
                    x, pitch_target, mel_mask, p_control
                )
                if self.use_variance_embeddings["pitch"]:
                    x = x + pitch_embedding
            else:
                pitch_prediction = None

        if self.energy_feature_level == "frame_level":
            if self.use_variance_predictor["energy"]:
                energy_prediction, energy_embedding = self.get_energy_embedding(
                    x, energy_target, mel_mask, e_control
                )
                if self.use_variance_embeddings["energy"]:
                    x = x + energy_embedding
            else:
                energy_prediction = None

        return (
            x,
            x_au,
            pitch_prediction,
            energy_prediction,
            log_duration_prediction,
            duration_rounded,
            mel_len,
            mel_mask,
            output_by_layer,
            self.pitch_embedding,
            self.pitch_bins,
        )


class LengthRegulator(nn.Module):
    """Length Regulator"""

    def __init__(self):
        super(LengthRegulator, self).__init__()

    def LR(self, x, duration, max_len):
        output = list()
        mel_len = list()
        for batch, expand_target in zip(x, duration):
            expanded = self.expand(batch, expand_target)
            output.append(expanded)
            mel_len.append(expanded.shape[0])

        if max_len is not None:
            output = pad(output, max_len)
        else:
            output = pad(output)

        return output, torch.LongTensor(mel_len).to(device)

    def expand(self, batch, predicted):
        out = list()

        for i, vec in enumerate(batch):
            expand_size = predicted[i].item()

            # out.append(vec.expand(max(int(expand_size), 0), -1))
            out.append(vec.expand(max(int(np.round(expand_size)), 0), -1))

        out = torch.cat(out, 0)

        return out

    def forward(self, x, duration, max_len):
        output, mel_len = self.LR(x, duration, max_len)
        return output, mel_len


class VariancePredictor(nn.Module):
    """Duration, Pitch and Energy Predictor"""

    def __init__(self, model_config):
        super(VariancePredictor, self).__init__()

        self.input_size = model_config["transformer"]["encoder_hidden"]
        self.filter_size = model_config["variance_predictor"]["filter_size"]
        self.kernel = model_config["variance_predictor"]["kernel_size"]
        self.conv_output_size = model_config["variance_predictor"]["filter_size"]
        self.dropout = model_config["variance_predictor"]["dropout"]

        self.conv_layer = nn.Sequential(
            OrderedDict(
                [
                    (
                        "conv1d_1",
                        Conv(
                            self.input_size,
                            self.filter_size,
                            kernel_size=self.kernel,
                            padding=(self.kernel - 1) // 2,
                        ),
                    ),
                    ("relu_1", nn.ReLU()),
                    ("layer_norm_1", nn.LayerNorm(self.filter_size)),
                    ("dropout_1", nn.Dropout(self.dropout)),
                    (
                        "conv1d_2",
                        Conv(
                            self.filter_size,
                            self.filter_size,
                            kernel_size=self.kernel,
                            padding=1,
                        ),
                    ),
                    ("relu_2", nn.ReLU()),
                    ("layer_norm_2", nn.LayerNorm(self.filter_size)),
                    ("dropout_2", nn.Dropout(self.dropout)),
                ]
            )
        )

        self.linear_layer = nn.Linear(self.conv_output_size, 1)

    def forward(self, encoder_output, mask):
        out = self.conv_layer(encoder_output)
        out = self.linear_layer(out)
        out = out.squeeze(-1)

        if mask is not None:
            out = out.masked_fill(mask, 0.0)

        return out

class EmbeddingBias(object):
    """
    Bias Module to control acoustic params from embeddings analysis
    """
    def __init__(self, model_config):
        self.bias_vector_name = model_config["bias_vector"]["bias_vector_name"]
        self.layer_by_param = model_config["bias_vector"]["layer_by_param"]
        self.default_control_bias_array = model_config["bias_vector"]["value_by_param"]
        
    def layer_control_by_param(self, embeddings, control_bias_value, index_param, layer_index, indexes_utt_in_batch_to_apply_bias='all', indexes_target_char_in_utt_to_apply_bias='all', is_acoustic=True):
        embeddings_size = embeddings.size()
        embeddings_dim = embeddings.dim()
                
        load_bias_vector = loadmat(self.bias_vector_name) # vector name: bias_vector_by_layer
        bias_vector = load_bias_vector['bias_vector_by_layer'][layer_index-1][0][:, index_param].transpose()
        bias_size = len(bias_vector)
                
        if index_param == 0 and is_acoustic:
            bias_vector = bias_vector*(np.log(control_bias_value))
        else:
            bias_vector = bias_vector*control_bias_value
                    
        if embeddings_dim == 2: # frame by frame
            bias_vector = bias_vector[np.newaxis,:]
            bias_vector = torch.FloatTensor(bias_vector)
            bias_vector = bias_vector.to(device)
            embeddings = embeddings + bias_vector
        else:
            dim_bias = embeddings_size.index(bias_size)  
            dim_repeat = 1 if dim_bias==2 else 2
            lg_repeat = embeddings.size(dim_repeat)
                    
            zero_bias_vector = np.zeros([embeddings.size(0), embeddings.size(1), embeddings.size(2)])
            
            if len(indexes_utt_in_batch_to_apply_bias) == 0:
                return embeddings

            if indexes_utt_in_batch_to_apply_bias=='all':
                indexes_utt_in_batch_to_apply_bias = np.sort([*range(embeddings.size(0))]*lg_repeat)
            if indexes_target_char_in_utt_to_apply_bias=='all':
                indexes_target_char_in_utt_to_apply_bias = [*range(lg_repeat)]*embeddings.size(0)
            if dim_bias == 1:
                zero_bias_vector[indexes_utt_in_batch_to_apply_bias, :, indexes_target_char_in_utt_to_apply_bias] = bias_vector

            elif dim_bias == 2:
                zero_bias_vector[indexes_utt_in_batch_to_apply_bias, indexes_target_char_in_utt_to_apply_bias, :] = bias_vector

            zero_bias_vector = torch.FloatTensor(zero_bias_vector)
            zero_bias_vector = zero_bias_vector.to(device)
            embeddings = embeddings + zero_bias_vector

        return embeddings

    def layer_control(self, embeddings, control_bias_array, layer_index, indexes_utt_in_batch_to_apply_bias='all', indexes_target_char_in_utt_to_apply_bias='all'):
        if control_bias_array == self.default_control_bias_array:
            return embeddings

        for index_param, layer_index_by_param in enumerate(self.layer_by_param):
            if layer_index_by_param == layer_index:
                embeddings = self.layer_control_by_param(embeddings, control_bias_array[index_param], index_param, layer_index, indexes_utt_in_batch_to_apply_bias, indexes_target_char_in_utt_to_apply_bias)
        return embeddings

class EmbeddingBiasCategorical(EmbeddingBias):
    """
    Bias Module to control categorical params (silences, liaisons) from embeddings analysis
    """

    def __init__(self, model_config):
        super(EmbeddingBias, self).__init__()

        self.bias_vector_name = model_config["bias_vector"]["categorical_bias_vector_name"]
        self.layer_by_param = model_config["bias_vector"]["layer_by_param_categorical"]
        self.default_control_bias_array = model_config["bias_vector"]["value_by_param_categorical"]

    def layer_control_on_patterns(self, embeddings, categorical_control_bias_array, layer_index, texts):
        index_silences = 0
        index_liaisons = 1
        
        # Silence Bias
        if categorical_control_bias_array[index_silences] != self.default_control_bias_array[index_silences] and self.layer_by_param[index_silences] == layer_index:
            list_patterns_silences = np.array([
                (' ', 0),
                (',', 0),
                ('.', 0),
                ('?', 0),
                ('!', 0),
                (':', 0),
                (';', 0),
                ('§', 0),
                ('~', 0),
                ('[', 0),
                (']', 0),
                ('(', 0),
                (')', 0),
                ('-', 0),
                ('"', 0),
                ('¬', 0),
                ('«', 0),
                ('»', 0),
            ])
            [silences_indexes_utt_in_batch, silences_indexes_target_char_in_utt] = _find_pattern_indexes_in_batch(list_patterns_silences, texts)
            embeddings = self.layer_control_by_param(embeddings, categorical_control_bias_array[index_silences], index_silences, layer_index, silences_indexes_utt_in_batch, silences_indexes_target_char_in_utt, is_acoustic=False)

        if categorical_control_bias_array[index_liaisons] != self.default_control_bias_array[index_liaisons] and self.layer_by_param[index_liaisons] == layer_index:
            list_patterns_liaisons = np.array([
                ('er a', 1),
                ('er à', 1),
                ('er e', 1),
                ('er i', 1),
                ('er o', 1),
                ('er u', 1),
                ('er y', 1),
                ('t a', 0),
                ('t e', 0),
                ('t i', 0),
                ('t o', 0),
                ('t u', 0),
                ('t y', 0),
                ('n a', 0),
                ('n â', 0),
                ('n e', 0),
                ('n i', 0),
                ('n o', 0),
                ('n u', 0),
                ('n y', 0),
                ('es a', 1),
                ('es e', 1),
                ('es i', 1),
                ('es o', 1),
                ('es u', 1),
                ('es y', 1),
            ])
            [liaisons_indexes_utt_in_batch, liaisons_indexes_target_char_in_utt] = _find_pattern_indexes_in_batch(list_patterns_liaisons, texts)
            embeddings = self.layer_control_by_param(embeddings, categorical_control_bias_array[index_liaisons], index_liaisons, layer_index, liaisons_indexes_utt_in_batch, liaisons_indexes_target_char_in_utt, is_acoustic=False)

        return embeddings

class Conv(nn.Module):
    """
    Convolution Module
    """

    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size=1,
        stride=1,
        padding=0,
        dilation=1,
        bias=True,
        w_init="linear",
    ):
        """
        :param in_channels: dimension of input
        :param out_channels: dimension of output
        :param kernel_size: size of kernel
        :param stride: size of stride
        :param padding: size of padding
        :param dilation: dilation rate
        :param bias: boolean. if True, bias is included.
        :param w_init: str. weight inits with xavier initialization.
        """
        super(Conv, self).__init__()

        self.conv = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=padding,
            dilation=dilation,
            bias=bias,
            # padding_mode='replicate',
        )

    def forward(self, x):
        x = x.contiguous().transpose(1, 2)
        x = self.conv(x)
        x = x.contiguous().transpose(1, 2)

        return x

class LinearNorm(nn.Module):
    def __init__(self, in_dim, out_dim, bias=True, w_init_gain='linear'):
        super(LinearNorm, self).__init__()
        self.linear_layer = nn.Linear(in_dim, out_dim, bias=bias)

        torch.nn.init.xavier_uniform_(
            self.linear_layer.weight,
            gain=nn.init.calculate_gain(w_init_gain))

    def forward(self, x):
        # return F.softmax(self.linear_layer(x), dim=2)
        return self.linear_layer(x) # CrossEntropyLoss computes softmax internally

