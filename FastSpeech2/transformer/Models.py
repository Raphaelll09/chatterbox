import torch
import torch.nn as nn
import numpy as np

import transformer.Constants as Constants
from .Layers import FFTBlock
from text.symbols import symbols

from model.modules import EmbeddingBias, EmbeddingBiasCategorical, get_sinusoid_encoding_table

class Encoder(nn.Module):
    """ Encoder """

    def __init__(self, config):
        super(Encoder, self).__init__()

        n_position = config["max_seq_len"] + 1
        n_src_vocab = len(symbols) + 1
        d_word_vec = config["transformer"]["encoder_hidden"]
        n_layers = config["transformer"]["encoder_layer"]
        n_head = config["transformer"]["encoder_head"]
        d_k = d_v = (
            config["transformer"]["encoder_hidden"]
            // config["transformer"]["encoder_head"]
        )
        d_model = config["transformer"]["encoder_hidden"]
        d_inner = config["transformer"]["conv_filter_size"]
        kernel_size = config["transformer"]["conv_kernel_size"]
        dropout = config["transformer"]["encoder_dropout"]

        self.max_seq_len = config["max_seq_len"]
        self.d_model = d_model

        self.src_word_emb = nn.Embedding(
            n_src_vocab, d_word_vec, padding_idx=Constants.PAD
        )
        self.position_enc = nn.Parameter(
            get_sinusoid_encoding_table(n_position, d_word_vec).unsqueeze(0),
            requires_grad=False,
        )

        self.layer_stack = nn.ModuleList(
            [
                FFTBlock(
                    d_model, n_head, d_k, d_v, d_inner, kernel_size, dropout=dropout
                )
                for _ in range(n_layers)
            ]
        )
        self.embedding_bias = EmbeddingBias(config)
        self.embedding_bias_categorical = EmbeddingBiasCategorical(config)
        self.save_embeddings_by_layer = config["save_embeddings_by_layer"]

    def forward(self, src_seq, mask, return_attns=False, control_bias_array=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], categorical_control_bias_array=[0.0, 0.0]):

        enc_slf_attn_list = []
        batch_size, max_len = src_seq.shape[0], src_seq.shape[1]

        # -- Prepare masks
        slf_attn_mask = mask.unsqueeze(1).expand(-1, max_len, -1)

        # -- Forward
        enc_output = self.src_word_emb(src_seq)
        enc_output_by_layer = self.src_word_emb(src_seq).unsqueeze(0)
        
        if not self.training and src_seq.shape[1] > self.max_seq_len:   
            pos_enc = get_sinusoid_encoding_table(
                src_seq.shape[1], self.d_model
            )[: src_seq.shape[1], :].unsqueeze(0).expand(batch_size, -1, -1).to(
                src_seq.device
            )
        else:
            pos_enc = self.position_enc[
                :, :max_len, :
            ].expand(batch_size, -1, -1)
            
        enc_output = enc_output + pos_enc

        if self.save_embeddings_by_layer and not self.training:
            enc_output_by_layer = torch.cat((enc_output_by_layer, enc_output.unsqueeze(0)), 0)
        
        encoder_layer_index = 2
        for enc_layer in self.layer_stack:
            enc_output, enc_slf_attn = enc_layer(
                enc_output, mask=mask, slf_attn_mask=slf_attn_mask
            )
            if return_attns:
                enc_slf_attn_list += [enc_slf_attn]
                
            encoder_layer_index += 1
            
            if not self.training: 
                # Add Embedding Bias layer in encoder
                enc_output = self.embedding_bias.layer_control(enc_output, control_bias_array, encoder_layer_index)

                # Add Categorical Embedding Bias layer in encoder
                enc_output = self.embedding_bias_categorical.layer_control_on_patterns(enc_output, categorical_control_bias_array, encoder_layer_index, src_seq)
                
            if self.save_embeddings_by_layer and not self.training:
                enc_output_by_layer = torch.cat((enc_output_by_layer, enc_output.unsqueeze(0)), 0)

        return enc_output, enc_output_by_layer


class Decoder(nn.Module):
    """ Decoder """

    def __init__(self, config):
        super(Decoder, self).__init__()

        n_position = config["max_seq_len"] + 1
        d_word_vec = config["transformer"]["encoder_hidden"]
        n_layers = config["transformer"]["decoder_layer"]
        n_head = config["transformer"]["decoder_head"]
        d_k = d_v = (
            config["transformer"]["decoder_hidden"]
            // config["transformer"]["decoder_head"]
        )
        d_model = config["transformer"]["decoder_hidden"]
        d_inner = config["transformer"]["conv_filter_size"]
        kernel_size = config["transformer"]["conv_kernel_size"]
        dropout = config["transformer"]["decoder_dropout"]

        self.max_seq_len = config["max_seq_len"]
        self.d_model = d_model

        self.position_enc = nn.Parameter(
            get_sinusoid_encoding_table(n_position, d_word_vec).unsqueeze(0),
            requires_grad=False,
        )

        self.layer_stack = nn.ModuleList(
            [
                FFTBlock(
                    d_model, n_head, d_k, d_v, d_inner, kernel_size, dropout=dropout
                )
                for _ in range(n_layers)
            ]
        )
        self.embedding_bias = EmbeddingBias(config)
        self.save_embeddings_by_layer = config["save_embeddings_by_layer"]

    def forward(self, enc_seq, mask, return_attns=False, control_bias_array=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]):

        dec_slf_attn_list = []
        batch_size, max_len = enc_seq.shape[0], enc_seq.shape[1]

        # -- Forward
        if not self.training and enc_seq.shape[1] > self.max_seq_len:
            # -- Prepare masks
            slf_attn_mask = mask.unsqueeze(1).expand(-1, max_len, -1)
            
            pos_enc = get_sinusoid_encoding_table(
                enc_seq.shape[1], self.d_model
            )[: enc_seq.shape[1], :].unsqueeze(0).expand(batch_size, -1, -1).to(
                enc_seq.device
            )
            
            dec_output = enc_seq + pos_enc
        
            if self.save_embeddings_by_layer:
                dec_output_by_layer = enc_seq.unsqueeze(0)
                dec_output_by_layer = torch.cat((dec_output_by_layer, dec_output.unsqueeze(0)), 0)
            else:
                dec_output_by_layer = None
            
        else:
            max_len = min(max_len, self.max_seq_len)

            # -- Prepare masks
            slf_attn_mask = mask.unsqueeze(1).expand(-1, max_len, -1)
            
            pos_enc = self.position_enc[
                :, :max_len, :
            ].expand(batch_size, -1, -1)
            
            dec_output = enc_seq[:, :max_len, :] + pos_enc
            mask = mask[:, :max_len]
            slf_attn_mask = slf_attn_mask[:, :, :max_len]
            
            if self.save_embeddings_by_layer and not self.training:
                dec_output_by_layer = enc_seq[:, :max_len, :].unsqueeze(0)
                dec_output_by_layer = torch.cat((dec_output_by_layer, dec_output.unsqueeze(0)), 0)
            else:
                dec_output_by_layer = None

        decoder_layer_index = 11
        for dec_layer in self.layer_stack:
            
            decoder_layer_index += 1
            
            if not self.training:
                # Add Embedding Bias layer in decoder
                dec_output = self.embedding_bias.layer_control(dec_output, control_bias_array, decoder_layer_index)
            
            dec_output, dec_slf_attn = dec_layer(
                dec_output, mask=mask, slf_attn_mask=slf_attn_mask
            )
            if return_attns:
                dec_slf_attn_list += [dec_slf_attn]

            if self.save_embeddings_by_layer and not self.training:   
                dec_output_by_layer = torch.cat((dec_output_by_layer, dec_output.unsqueeze(0)), 0)

        return dec_output, mask, dec_output_by_layer

class DecoderVisual(Decoder, nn.Module):
    """ Visual Decoder | Same architecture as Decoder, but different hyperparameters """

    def __init__(self, config):
        super(Decoder, self).__init__()

        n_position = config["max_seq_len"] + 1
        d_word_vec = config["transformer"]["encoder_hidden"]
        n_layers = config["visual_decoder"]["decoder_layer"]
        n_head = config["visual_decoder"]["decoder_head"]
        d_k = d_v = (
            config["visual_decoder"]["decoder_hidden"]
            // config["visual_decoder"]["decoder_head"]
        )
        d_model = config["visual_decoder"]["decoder_hidden"]
        d_inner = config["visual_decoder"]["conv_filter_size"]
        kernel_size = config["visual_decoder"]["conv_kernel_size"]
        dropout = config["visual_decoder"]["decoder_dropout"]

        self.max_seq_len = config["max_seq_len"]
        self.d_model = d_model

        self.position_enc = nn.Parameter(
            get_sinusoid_encoding_table(n_position, d_word_vec).unsqueeze(0),
            requires_grad=False,
        )

        self.layer_stack = nn.ModuleList(
            [
                FFTBlock(
                    d_model, n_head, d_k, d_v, d_inner, kernel_size, dropout=dropout
                )
                for _ in range(n_layers)
            ]
        )
        self.embedding_bias = EmbeddingBias(config)
        self.save_embeddings_by_layer = config["save_embeddings_by_layer"]