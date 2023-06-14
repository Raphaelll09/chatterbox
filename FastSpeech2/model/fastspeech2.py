import os
import json

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

from transformer import Encoder, Decoder, PostNet, DecoderVisual
from .modules import VarianceAdaptor, LinearNorm, EmbeddingBias, EmbeddingBiasCategorical, GST, LST
from utils.tools import get_mask_from_lengths
from scipy.io import loadmat

from text.symbols import out_symbols

#device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device = torch.device("cpu")

class FastSpeech2(nn.Module):
    """ FastSpeech2 """

    def __init__(self, preprocess_config, model_config, mode_batch=False):
        super(FastSpeech2, self).__init__()
        self.model_config = model_config

        self.encoder = Encoder(model_config)
        self.variance_adaptor = VarianceAdaptor(preprocess_config, model_config, mode_batch)
        self.decoder = Decoder(model_config)
        self.mel_linear = nn.Linear(
            model_config["transformer"]["decoder_hidden"],
            preprocess_config["preprocessing"]["mel"]["n_mel_channels"],
        )
        self.postnet = PostNet(n_mel_channels=preprocess_config["preprocessing"]["mel"]["n_mel_channels"])
        self.compute_phon_prediction = model_config["compute_phon_prediction"]
        self.compute_visual_prediction = model_config["visual_prediction"]["compute_visual_prediction"]
        self.visual_postnet = model_config["visual_prediction"]["visual_postnet"]
        self.separate_visual_decoder = model_config["visual_prediction"]["separate_visual_decoder"]

        # Phonetic prediction from input
        if self.compute_phon_prediction:
            self.dim_out_symbols = len(out_symbols)
            self.phonetize = LinearNorm(model_config["transformer"]["encoder_hidden"], self.dim_out_symbols)

        # Action Units prediction
        if self.compute_visual_prediction:
            if self.separate_visual_decoder:
                self.decoder_visual = DecoderVisual(model_config)
                self.au_linear = nn.Linear(
                    model_config["visual_decoder"]["decoder_hidden"],
                    preprocess_config["preprocessing"]["au"]["n_units"],
                )
            else:
                self.au_linear = nn.Linear(
                    model_config["transformer"]["decoder_hidden"],
                    preprocess_config["preprocessing"]["au"]["n_units"],
                )

            if self.visual_postnet:
                self.postnet_visual = PostNet(n_mel_channels=preprocess_config["preprocessing"]["au"]["n_units"])

        self.speaker_emb = None
        if model_config["multi_speaker"]:
            if mode_batch:
                config_preprocessed_path = preprocess_config["path"]["preprocessed_path_batch"]
            else:
                config_preprocessed_path = preprocess_config["path"]["preprocessed_path"]

            with open(
                os.path.join(
                    config_preprocessed_path, "speakers.json"
                ),
                "r",
            ) as f:
                n_speaker = len(json.load(f))
            self.speaker_emb = nn.Embedding(
                n_speaker,
                model_config["transformer"]["encoder_hidden"],
            )
        
        self.save_embeddings_by_layer = model_config["save_embeddings_by_layer"]

        self.embedding_bias = EmbeddingBias(model_config)
        self.embedding_bias_categorical = EmbeddingBiasCategorical(model_config)
        
        self.use_gst = model_config["gst"]["use_gst"]
        if self.use_gst:
            self.gst = GST(preprocess_config, model_config)

        self.use_lst = model_config["lst"]["use_lst"]
        if self.use_lst:
            self.lst = LST(model_config)
            self.add_gst = model_config["lst"]["add_gst"]
            self.lst_scale = model_config["lst"]["scale"]

    def forward(
        self,
        speakers,
        texts,
        src_lens,
        max_src_len,
        mels=None,
        mel_lens=None,
        max_mel_len=None,
        p_targets=None,
        e_targets=None,
        d_targets=None,
        phon_align_targets=None,
        au_targets=None,
        au_lens=None,
        max_au_len=None,
        emotion_vector=None,
        inference_gst_token_vector=None,
        p_control=0.0,
        e_control=0.0,
        d_control=1.0,
        control_bias_array=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        categorical_control_bias_array=[0.0, 0.0],
    ):

        src_masks = get_mask_from_lengths(src_lens, max_src_len)
        mel_masks = (
            get_mask_from_lengths(mel_lens, max_mel_len)
            if mel_lens is not None
            else None
        )
        au_masks = (
            get_mask_from_lengths(au_lens, max_mel_len)
            if au_lens is not None
            else None
        )

        output, enc_output_by_layer = self.encoder(texts, src_masks, control_bias_array=control_bias_array, categorical_control_bias_array=categorical_control_bias_array)
        
        # GST
        if self.use_gst:
            style_embedding, gst_token_attention_scores, unnormalized_gst_token_attention_scores = self.gst(mels, mel_lens, inference_gst_token_vector)
            #print(style_embedding.shape)
            #print(gst_token_attention_scores.shape)
            #print(output.shape)
            
            style_emb_output = style_embedding.expand(
                -1, max_src_len, -1
            )

            if self.use_lst and self.add_gst:
                output = output + style_emb_output
            else:
                output = output + style_emb_output
        else:
            gst_token_attention_scores = None
            unnormalized_gst_token_attention_scores = None

        if self.speaker_emb is not None:
            output = output + self.speaker_emb(speakers).unsqueeze(1).expand(
                -1, max_src_len, -1
            )
            if self.save_embeddings_by_layer and not self.training:
                enc_output_by_layer = torch.cat((enc_output_by_layer, output.unsqueeze(0)), 0)
        else:
            if self.save_embeddings_by_layer and not self.training:
                enc_output_by_layer = torch.cat((enc_output_by_layer, enc_output_by_layer[-1, :, :, :].unsqueeze(0)), 0)
            
        if not self.training:
            # Add Embedding Bias layer 7
            output = self.embedding_bias.layer_control(output, control_bias_array, 7)

            # Add Categorical Embedding Bias layer 7
            output = self.embedding_bias_categorical.layer_control_on_patterns(output, categorical_control_bias_array, 7, texts)

        # LST
        if self.use_lst:
            if self.lst_scale == "phone":
                positional_indexes = torch.arange(0, output.shape[1], dtype=int).unsqueeze(0).expand(output.shape[0], -1).to(device)
                if self.add_gst:
                    local_style_embedding, lst_token_attention_scores = self.lst(output, positional_indexes)
                else:
                    # Concat GST to LST inputs
                    local_style_embedding, lst_token_attention_scores = self.lst(torch.cat((output, style_emb_output), 2), positional_indexes)
            elif self.lst_scale == "word":
                output_by_word, positional_indexes = self.lst.compute_embeddings_by_word(output, texts)
                if self.add_gst:
                    local_style_embedding, lst_token_attention_scores = self.lst(output_by_word, positional_indexes)
                else:
                    # Concat GST to LST inputs
                    local_style_embedding, lst_token_attention_scores = self.lst(torch.cat((output_by_word, style_emb_output), 2), positional_indexes)

            output = output + local_style_embedding
        else:
            lst_token_attention_scores = None

        if self.compute_phon_prediction:
            phon_outputs = self.phonetize(output).transpose(1,2)
        else:
            phon_outputs = None

        (
            output,
            output_au,
            p_predictions,
            e_predictions,
            log_d_predictions,
            d_rounded,
            mel_lens,
            mel_masks,
            output_by_layer_variance_adaptor,
            pitch_embeddings,
            pitch_bins,
        ) = self.variance_adaptor(
            output,
            src_masks,
            mel_masks,
            max_mel_len,
            p_targets,
            e_targets,
            d_targets,
            p_control,
            e_control,
            d_control,
            control_bias_array,
        )

        if self.save_embeddings_by_layer and not self.training:
            enc_output_by_layer = torch.cat((enc_output_by_layer, output_by_layer_variance_adaptor), 0)
        
        output, mel_masks, dec_output_by_layer = self.decoder(output, mel_masks)
        
        # Action Units prediction
        if self.compute_visual_prediction:
            if self.separate_visual_decoder:
                output_au, au_masks, visual_dec_output_by_layer = self.decoder_visual(output_au, mel_masks)
                output_au = self.au_linear(output_au)
            else:
                output_au = self.au_linear(output)

            if self.save_embeddings_by_layer and not self.training:    
                au_output_by_layer = output_au.unsqueeze(0)
            else:
                au_output_by_layer = None

            if self.visual_postnet:
                postnet_output_au, postnet_output_by_layer_au = self.postnet_visual(output_au)
                postnet_output_au = postnet_output_au + output_au

                if self.save_embeddings_by_layer and not self.training:
                    au_output_by_layer = torch.cat((au_output_by_layer, postnet_output_au.unsqueeze(0)), 0)
            else:
                postnet_output_au = None
                postnet_output_by_layer_au = None
                if self.save_embeddings_by_layer and not self.training:
                    au_output_by_layer = torch.cat((au_output_by_layer, au_output_by_layer[-1, :, :, :].unsqueeze(0)), 0)
        else:
            output_au = None
            postnet_output_au = None
            visual_dec_output_by_layer = None
            postnet_output_by_layer_au = None
            au_output_by_layer = None
            au_masks = None

        output = self.mel_linear(output)
        if self.save_embeddings_by_layer and not self.training:
            mel_output_by_layer = output.unsqueeze(0)
        else:
            mel_output_by_layer = None

        postnet_output, postnet_output_by_layer = self.postnet(output)
        postnet_output = postnet_output + output

        if self.save_embeddings_by_layer and not self.training:
            mel_output_by_layer = torch.cat((mel_output_by_layer, postnet_output.unsqueeze(0)), 0)

        return (
            output,
            postnet_output,
            p_predictions,
            e_predictions,
            log_d_predictions,
            d_rounded,
            src_masks,
            mel_masks,
            src_lens,
            mel_lens,
            [enc_output_by_layer, dec_output_by_layer, postnet_output_by_layer, mel_output_by_layer, visual_dec_output_by_layer, postnet_output_by_layer_au, au_output_by_layer],
            pitch_embeddings,
            pitch_bins,
            phon_outputs,
            output_au,
            postnet_output_au,
            au_masks,
            au_lens,
            gst_token_attention_scores,
            unnormalized_gst_token_attention_scores,
            lst_token_attention_scores,
        )
