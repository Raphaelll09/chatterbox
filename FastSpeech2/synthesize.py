import re
import argparse
from string import punctuation
import os
import json

import torch
import yaml
import numpy as np
from torch.utils.data import DataLoader
from g2p_en import G2p
from pypinyin import pinyin, Style

from utils.model import get_model, get_vocoder
from utils.tools import to_device, synth_samples, expand, plot_mel
from dataset import TextDataset, Dataset
from text import text_to_sequence, out_symbols

from matplotlib import pyplot as plt

from scipy.io import loadmat
from scipy.io import savemat

# device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
device = torch.device("cpu")
index_syn = 0

def read_lexicon(lex_path):
    lexicon = {}
    with open(lex_path) as f:
        for line in f:
            temp = re.split(r"\s+", line.strip("\n"))
            word = temp[0]
            phones = temp[1:]
            if word.lower() not in lexicon:
                lexicon[word.lower()] = phones
    return lexicon


def preprocess_english(text, preprocess_config):
    text = text.rstrip(punctuation)
    lexicon = read_lexicon(preprocess_config["path"]["lexicon_path"])

    g2p = G2p()
    phones = []
    words = re.split(r"([,;.\-\?\!\s+])", text)
    for w in words:
        if w.lower() in lexicon:
            phones += lexicon[w.lower()]
        else:
            phones += list(filter(lambda p: p != " ", g2p(w)))
    phones = "{" + "}{".join(phones) + "}"
    phones = re.sub(r"\{[^\w\s]?\}", "{sp}", phones)
    phones = phones.replace("}{", " ")

    print("Raw Text Sequence: {}".format(text))
    print("Phoneme Sequence: {}".format(phones))
    sequence = np.array(
        text_to_sequence(
            phones, preprocess_config["preprocessing"]["text"]["text_cleaners"]
        )
    )

    return np.array(sequence)

def preprocess_french(text, preprocess_config):
    text = text.rstrip(punctuation)
    text = text.rstrip("01")
    lexicon = read_lexicon(preprocess_config["path"]["lexicon_path"])

    g2p = G2p()
    phones = []
    # Split for english: words = re.split(r"([,;.\-\?\!\s+])", text)
    words = re.split(r"([,;.¬:§~«»#\"\(\)\[\]\?\!\s+])", text)
    for w in words:
        if w.lower() in lexicon:
            phones += lexicon[w.lower()]
        else:
            phones += list(filter(lambda p: p != " ", g2p(w)))
    phones = "{" + "}{".join(phones) + "}"
    phones = re.sub(r"\{[^\w\s]?\}", "{sp}", phones)
    phones = phones.replace("}{", " ")

    print("Raw Text Sequence: {}".format(text))
    print("Phoneme Sequence: {}".format(phones))
    sequence = np.array(
        text_to_sequence(
            phones, preprocess_config["preprocessing"]["text"]["text_cleaners"]
        )
    )

    return np.array(sequence)


def preprocess_mandarin(text, preprocess_config):
    lexicon = read_lexicon(preprocess_config["path"]["lexicon_path"])

    phones = []
    pinyins = [
        p[0]
        for p in pinyin(
            text, style=Style.TONE3, strict=False, neutral_tone_with_five=True
        )
    ]
    for p in pinyins:
        if p in lexicon:
            phones += lexicon[p]
        else:
            phones.append("sp")

    phones = "{" + " ".join(phones) + "}"
    print("Raw Text Sequence: {}".format(text))
    print("Phoneme Sequence: {}".format(phones))
    sequence = np.array(
        text_to_sequence(
            phones, preprocess_config["preprocessing"]["text"]["text_cleaners"]
        )
    )

    return np.array(sequence)

def process_per_batch(
    batch, 
    model, 
    pitch_control, 
    energy_control, 
    duration_control, 
    output_wav, 
    vocoder, 
    model_config, 
    preprocess_config, 
    train_config, 
    extension_data,
    mel_dim,
    teacher_forcing,
    control_bias_array,
    categorical_control_bias_array,
    mode_batch=False,
):
    batch = to_device(batch, device)

    with torch.no_grad():
        # Forward
        output = model(
            *(batch[2:6]),
            p_control=pitch_control,
            e_control=energy_control,
            d_control=duration_control,
            control_bias_array=control_bias_array,
            categorical_control_bias_array=categorical_control_bias_array,
            inference_gst_token_vector=batch[7],
        )

        if output_wav:
            synth_samples(
                batch,
                output,
                vocoder,
                model_config,
                preprocess_config,
                train_config["path"]["result_path"],
            )
        else:
            if mode_batch:
                output_syn_path = preprocess_config["path"]["output_syn_path_batch"]
            else:
                output_syn_path = preprocess_config["path"]["output_syn_path"]

            for i in range(len(output[0])):
                # print(batch)
                basename = batch[0][i]
                global index_syn
                index_syn += 1
                # basename = "TEST{:05d}_syn".format(index_syn)
                
                src_len = output[8][i].item()
                mel_len = output[9][i].item()
                mel_prediction = output[1][i, :mel_len].detach().transpose(0, 1).cpu().data.numpy().transpose()
                # print(mel_prediction)

                if teacher_forcing:
                    mel_target = batch[6][i, :mel_len].detach().transpose(0, 1).cpu().data.numpy().transpose()
                    pitch_target = batch[9][i, :src_len].detach().cpu().data.numpy().transpose()
                    energy_target = batch[10][i, :src_len].detach().cpu().data.numpy().transpose()
                    duration_target = batch[11][i, :src_len].detach().cpu().data.numpy().transpose()

                    # print(mel_target)
                    # Copy of the spectrum in a file
                    fp = open('{}/{}_reconstruction.{}'.format(output_syn_path, basename, extension_data), 'wb')
                    fp.write(np.asarray((mel_len, mel_dim), dtype=np.int32))
                    fp.write(mel_target.copy(order='C'))
                    fp.close()
                    print('{}/{}_reconstruction.{} created'.format(output_syn_path, basename, extension_data), flush=True)

                    # save pitch_target in .mat format
                    mdic = {"pitch_prediction_mat": pitch_target}
                    nm_pitch = '{}/{}_pitch_target.mat'.format(output_syn_path, basename)
                    savemat(nm_pitch, mdic)

                    # save energy_target in .mat format
                    mdic = {"energy_prediction_mat": energy_target}
                    nm_energy = '{}/{}_energy_target.mat'.format(output_syn_path, basename)
                    savemat(nm_energy, mdic)

                    # save duration_target in .mat format
                    mdic = {"duration_mat": duration_target}
                    nm_duration = '{}/{}_duration_target.mat'.format(output_syn_path, basename)
                    savemat(nm_duration, mdic)

                # mel_prediction = output[1][i, :mel_len].cpu().data.numpy().reshape(mel_dim,-1).transpose()
                # print(len(mel_prediction))
                # print(len(mel_prediction[0]))
                # print(type(mel_prediction[0, 0]))
                # print(src_len)
                # print(mel_len)

                # Copy of the spectrum in a file
                if model_config["save_predictions"]["mel"]:
                    fp = open('{}/{}.{}'.format(output_syn_path, basename, extension_data), 'wb')
                    fp.write(np.asarray((mel_len, mel_dim), dtype=np.int32))
                    fp.write(mel_prediction.copy(order='C'))
                    fp.close()
                print('{}/{}.{} created'.format(output_syn_path, basename, extension_data), flush=True)

                mel_prediction = output[1][i, :mel_len].detach().transpose(0, 1)
                log_duration = output[4][i, :src_len].detach().cpu().numpy()
                duration = output[5][i, :src_len].detach().cpu().numpy()
                
                # Output by layer
                if model_config["save_embeddings_by_layer"]:
                    output_by_layer = output[10]
                    enc_output_by_layer = output_by_layer[0][:, i, :src_len].detach().cpu().numpy().transpose()
                    dec_output_by_layer = output_by_layer[1][:, i, :mel_len].detach().cpu().numpy().transpose()
                    #postnet_output_by_layer = output_by_layer[2][:, i, :mel_len].detach().cpu().numpy().transpose()
                    #mel_output_by_layer = output_by_layer[3][:, i, :mel_len].detach().cpu().numpy().transpose()

                if model_config["save_predictions"]["duration"]:
                    # save duration in .mat format
                    mdic = {"duration_mat": duration}
                    nm_duration = '{}/{}_duration.mat'.format(output_syn_path, basename)
                    savemat(nm_duration, mdic)

                    # save in .npy format
                    with open('{}/{}_duration.npy'.format(output_syn_path, basename), 'wb') as f:
                        np.save(f, np.array(duration))

                if model_config["save_predictions"]["log_duration"]:
                    # save log_duration in .mat format
                    mdic = {"log_duration_mat": log_duration}
                    nm_duration = '{}/{}_log_duration.mat'.format(output_syn_path, basename)
                    savemat(nm_duration, mdic)
                    
                    # save in .npy format
                    with open('{}/{}_log_duration.npy'.format(output_syn_path, basename), 'wb') as f:
                        np.save(f, np.array(log_duration))

                if model_config["save_embeddings_by_layer"]:
                    # save encoder embeddings in .mat format
                    mdic = {"enc_output_by_layer_mat": enc_output_by_layer}
                    nm_emb = '{}/{}_enc_emb_by_layer.mat'.format(output_syn_path, basename)
                    savemat(nm_emb, mdic)

                    # save dec embeddings in .mat format
                    mdic = {"dec_output_by_layer_mat": dec_output_by_layer}
                    nm_emb = '{}/{}_dec_emb_by_layer.mat'.format(output_syn_path, basename)
                    savemat(nm_emb, mdic)
                    
                    if False:
                        # save postnet embeddings in .mat format
                        mdic = {"postnet_output_by_layer_mat": postnet_output_by_layer}
                        nm_emb = '{}/{}_postnet_emb_by_layer.mat'.format(output_syn_path, basename)
                        savemat(nm_emb, mdic)
                        
                        # save mel before and after postnet in .mat format
                        mdic = {"mel_output_by_layer_mat": mel_output_by_layer}
                        nm_emb = '{}/{}_mel_by_layer.mat'.format(output_syn_path, basename)
                        savemat(nm_emb, mdic)

                if model_config["use_variance_predictor"]["pitch"] and model_config["save_predictions"]["pitch"]:
                    # save pitch prediction in .mat format
                    pitch_prediction = output[2][i, :src_len].detach().cpu().numpy().transpose()

                    mdic = {"pitch_prediction_mat": pitch_prediction}
                    nm_pitch = '{}/{}_pitch.mat'.format(output_syn_path, basename)
                    savemat(nm_pitch, mdic)

                if model_config["use_variance_predictor"]["energy"] and model_config["save_predictions"]["energy"]:
                    # save energy prediction in .mat format
                    energy_prediction = output[3][i, :src_len].detach().cpu().numpy().transpose()

                    mdic = {"energy_prediction_mat": energy_prediction}
                    nm_energy = '{}/{}_energy.mat'.format(output_syn_path, basename)
                    savemat(nm_energy, mdic)

                if model_config["compute_phon_prediction"] and model_config["save_predictions"]["phon"]:
                    if teacher_forcing:
                        phon_targets = batch[12][i, :src_len].detach().cpu().data.numpy().transpose()
                    else:
                        phon_targets = batch[6][i, :src_len].transpose()

                    phon_prediction = output[13][i, :, :src_len].detach().cpu().numpy()
                    ind_pred = phon_prediction.argmax(axis=0)

                    phon_pred = []
                    for p in range(len(phon_targets)):
                        if phon_targets[p]==-1:
                            phon_pred.append("None|{}".format(out_symbols[ind_pred[p]]))
                        else:
                            # print("{}|{}".format(out_symbols[phon_targets[p]], out_symbols[ind_pred[p]]))
                            phon_pred.append("{}|{}".format(out_symbols[phon_targets[p]], out_symbols[ind_pred[p]]))

                    mdic = {"phon_prediction_mat": phon_pred}
                    nm_phon_pred = '{}/{}_phon.mat'.format(output_syn_path, basename)
                    savemat(nm_phon_pred, mdic)

                if model_config["gst"]["use_gst"] and model_config["save_predictions"]["gst"]:
                    emotion_prediction = output[18][i, :].detach().cpu().numpy()

                    mdic = {"gst_prediction_mat": emotion_prediction}
                    nm_emotion = '{}/{}_gst.mat'.format(output_syn_path, basename)
                    savemat(nm_emotion, mdic)

                if model_config["lst"]["use_lst"] and model_config["save_predictions"]["lst"]:
                    emotion_prediction = output[20][i, :].detach().cpu().numpy()
                    
                    mdic = {"lst_prediction_mat": emotion_prediction}
                    nm_emotion = '{}/{}_lst.mat'.format(output_syn_path, basename)
                    savemat(nm_emotion, mdic)
                    
                if model_config["visual_prediction"]["compute_visual_prediction"] and model_config["save_predictions"]["au"]:
                    # au_len = output[17][i].item()
                    au_len = mel_len
                    au_prediction = output[15][i, :au_len].detach().transpose(0, 1).cpu().data.numpy().transpose()

                    # Copy of the action units in a file
                    extension_au = model_config["visual_prediction"]["extension"]
                    au_dim = preprocess_config["preprocessing"]["au"]["n_units"]
                    num = preprocess_config["preprocessing"]["audio"]["sampling_rate"]
                    den = preprocess_config["preprocessing"]["stft"]["hop_length"]

                    fp = open('{}/{}.{}'.format(output_syn_path, basename, extension_au), 'wb')
                    fp.write(np.asarray((au_len, au_dim, num, den), dtype=np.int32))
                    fp.write(au_prediction.copy(order='C'))
                    fp.close()
                    print('{}/{}.{} created'.format(output_syn_path, basename, extension_au), flush=True)
                    
                    if model_config["save_embeddings_by_layer"]:
                            visual_dec_output_by_layer = output_by_layer[4][:, i, :au_len].detach().cpu().numpy().transpose()
                            visual_postnet_output_by_layer = output_by_layer[5][:, i, :au_len].detach().cpu().numpy().transpose()
                            au_output_by_layer = output_by_layer[6][:, i, :au_len].detach().cpu().numpy().transpose()

                            # save dec embeddings in .mat format
                            mdic = {"visual_dec_output_by_layer_mat": visual_dec_output_by_layer}
                            nm_emb = '{}/{}_visual_dec_emb_by_layer.mat'.format(output_syn_path, basename)
                            savemat(nm_emb, mdic)
                            
                            # save postnet embeddings in .mat format
                            mdic = {"visual_postnet_output_by_layer_mat": visual_postnet_output_by_layer}
                            nm_emb = '{}/{}_visual_postnet_emb_by_layer.mat'.format(output_syn_path, basename)
                            savemat(nm_emb, mdic)
                            
                            # save mel before and after postnet in .mat format
                            mdic = {"au_output_by_layer_mat": au_output_by_layer}
                            nm_emb = '{}/{}_au_output_by_layer.mat'.format(output_syn_path, basename)
                            savemat(nm_emb, mdic)

                    if teacher_forcing:
                        # print(output[15][i, :au_len])
                        # print(batch[13][i, :au_len])
                        au_len = output[17][i].item()
                        au_target = batch[13][i, :au_len].detach().transpose(0, 1).cpu().data.numpy().transpose()
                        fp = open('{}/{}_reconstruction.{}'.format(output_syn_path, basename, extension_au), 'wb')
                        fp.write(np.asarray((au_len, au_dim, num, den), dtype=np.int32))
                        fp.write(au_target.copy(order='C'))
                        fp.close()
                        print('{}/{}_reconstruction.{} created'.format(output_syn_path, basename, extension_au), flush=True)


                if False:
                    if preprocess_config["preprocessing"]["pitch"]["feature"] == "phoneme_level":
                        pitch = output[2][i, :src_len].detach().cpu().numpy()
                        pitch = expand(pitch, duration)
                    else:
                        pitch = output[2][i, :mel_len].detach().cpu().numpy()
                    if preprocess_config["preprocessing"]["energy"]["feature"] == "phoneme_level":
                        energy = output[3][i, :src_len].detach().cpu().numpy()
                        energy = expand(energy, duration)
                    else:
                        energy = output[3][i, :mel_len].detach().cpu().numpy()

                    with open(
                        os.path.join(preprocess_config["path"]["preprocessed_path"], "stats.json")
                    ) as f:
                        stats = json.load(f)
                        stats = stats["pitch"] + stats["energy"][:2]

                    fig = plot_mel(
                        [
                            (mel_prediction.cpu().numpy(), pitch, energy),
                        ],
                        stats,
                        ["Synthetized Spectrogram"],
                    )
                    plt.savefig('output/spectro/{}.png'.format(basename))
                    plt.close()

            # Only once at the end
            if False:
                pitch_embeddings = output[11].weight.detach().cpu().numpy()
                # save duration in .mat format
                mdic = {"pitch_mat": pitch_embeddings}
                nm_pitch_mat = '{}/embeddings_pitch_mat.mat'.format(output_syn_path)
                savemat(nm_pitch_mat, mdic)

                pitch_bins = output[12].detach().cpu().numpy()
                # save duration in .mat format
                mdic = {"pitch_bins": pitch_bins}
                nm_pitch_bins_mat = '{}/pitch_bins_mat.mat'.format(output_syn_path)
                savemat(nm_pitch_bins_mat, mdic)

def synthesize(model, step, configs, vocoder, batchs, control_values, teacher_forcing, control_bias_array, categorical_control_bias_array, silence_control_bias=False, mode_batch=False):
    preprocess_config, model_config, train_config = configs
    pitch_control, energy_control, duration_control = control_values

    # Output of the model
    output_wav = train_config["output"]["wav"]
    extension_data = model_config["vocoder"]["model"]
    mel_dim = preprocess_config["preprocessing"]["mel"]["n_mel_channels"]

    if teacher_forcing:
        for sub_batchs in batchs:
            for batch in sub_batchs:
                process_per_batch(
                    batch, 
                    model, 
                    pitch_control, 
                    energy_control, 
                    duration_control, 
                    output_wav, 
                    vocoder, 
                    model_config, 
                    preprocess_config, 
                    train_config, 
                    extension_data,
                    mel_dim,
                    teacher_forcing,
                    control_bias_array,
                    categorical_control_bias_array,
                    mode_batch,
                )
    else:
        for batch in batchs:
            process_per_batch(
                batch, 
                model, 
                pitch_control, 
                energy_control, 
                duration_control, 
                output_wav, 
                vocoder, 
                model_config, 
                preprocess_config, 
                train_config, 
                extension_data,
                mel_dim,
                teacher_forcing,
                control_bias_array,
                categorical_control_bias_array,
                mode_batch,
            )


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--restore_step", type=int, required=True)
    parser.add_argument(
        "--mode",
        type=str,
        choices=["batch", "single"],
        required=True,
        help="Synthesize a whole dataset or a single sentence",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="path to a source file with format like train.txt and val.txt, for batch mode only",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="raw text to synthesize, for single-sentence mode only",
    )
    parser.add_argument(
        "--speaker_id",
        type=int,
        default=0,
        help="speaker ID for multi-speaker synthesis, for single-sentence mode only",
    )
    parser.add_argument(
        "-p",
        "--preprocess_config",
        type=str,
        required=True,
        help="path to preprocess.yaml",
    )
    parser.add_argument(
        "-m", "--model_config", type=str, required=True, help="path to model.yaml"
    )
    parser.add_argument(
        "-t", "--train_config", type=str, required=True, help="path to train.yaml"
    )
    parser.add_argument(
        "--pitch_control",
        type=float,
        default=0.0,
        help="control the pitch of the whole utterance, larger value for higher pitch",
    )
    parser.add_argument(
        "--energy_control",
        type=float,
        default=0.0,
        help="control the energy of the whole utterance, larger value for larger volume",
    )
    parser.add_argument(
        "--duration_control",
        type=float,
        default=1.0,
        help="control the speed of the whole utterance, larger value for slower speaking rate",
    )
    parser.add_argument(
        "--teacher_forcing",
        required=False,
        action='store_true',
        help="output spectrogram computed with teacher_forcing",
    )
    parser.add_argument(
        "--duration_control_bias",
        type=float,
        default=1.0,
        help="control the speed of the whole utterance, larger value for slower speaking rate",
    )
    parser.add_argument(
        "--pitch_control_bias",
        type=float,
        default=0.0,
        help="control the pitch of the whole utterance, larger value for higher pitch",
    )
    parser.add_argument(
        "--f1_control_bias",
        type=float,
        default=0.0,
        help="control the first formant of the whole utterance, larger value for higher pitch",
    )
    parser.add_argument(
        "--f2_control_bias",
        type=float,
        default=0.0,
        help="control the second formant of the whole utterance, larger value for higher pitch",
    )
    parser.add_argument(
        "--f3_control_bias",
        type=float,
        default=0.0,
        help="control the third formant of the whole utterance, larger value for higher pitch",
    )
    parser.add_argument(
        "--spectral_tilt_control_bias",
        type=float,
        default=0.0,
        help="control the spectral tilt of the whole utterance, higher value for tilt closer to 0",
    )
    parser.add_argument(
        "--energy_control_bias",
        type=float,
        default=0.0,
        help="control the energy of the whole utterance, larger value for higher energy",
    )
    parser.add_argument(
        "--relative_pos_control_bias",
        type=float,
        default=0.0,
        help="control the relative position of formant in current utt",
    )
    parser.add_argument(
        "--pfitzinger_control_bias",
        type=float,
        default=0.0,
        help="control the pfitzinger coefficient in current utt, relative to speech speed (higher value for faster speech)",
    )
    parser.add_argument(
        "--cog_control_bias",
        type=float,
        default=0.0,
        help="control the center of gravity (semitones) in current utt",
    )
    parser.add_argument(
        "--sb1k_control_bias",
        type=float,
        default=0.0,
        help="control the spectral balance between 1kHz (dB) in current utt",
    )
    parser.add_argument(
        "--pause_control_bias",
        type=float,
        default=0.0,
        help="control the proposion of the model to realize pauses between words",
    )
    parser.add_argument(
        "--liaison_control_bias",
        type=float,
        default=0.0,
        help="control the proposion of the model to realize liaisons between words",
    )
    parser.add_argument(
        "--silence_control_bias",
        required=False,
        action='store_true',
        help="Modify silences propoertion along duration control",
    )
    parser.add_argument(
        "--negative_control",
        required=False,
        action='store_true',
        help="negative control bias",
    )
    args = parser.parse_args()

    if args.negative_control:
        args.pitch_control = -args.pitch_control
        args.energy_control = -args.energy_control
        
        args.pitch_control_bias = -args.pitch_control_bias
        args.f1_control_bias = -args.f1_control_bias
        args.f2_control_bias = -args.f2_control_bias
        args.f3_control_bias = -args.f3_control_bias
        args.spectral_tilt_control_bias = -args.spectral_tilt_control_bias
        args.energy_control_bias = -args.energy_control_bias
        args.relative_pos_control_bias = -args.relative_pos_control_bias
        args.pfitzinger_control_bias = -args.pfitzinger_control_bias
        args.cog_control_bias = -args.cog_control_bias
        args.sb1k_control_bias = -args.sb1k_control_bias
        
        args.pause_control_bias = -args.pause_control_bias
        args.liaison_control_bias = -args.liaison_control_bias

    # Check source texts
    if args.mode == "batch":
        mode_batch = True
        assert args.source is not None and args.text is None
    if args.mode == "single":
        mode_batch = False
        assert args.source is None and args.text is not None

    # Read Config
    preprocess_config = yaml.load(
        open(args.preprocess_config, "r"), Loader=yaml.FullLoader
    )
    model_config = yaml.load(open(args.model_config, "r"), Loader=yaml.FullLoader)
    train_config = yaml.load(open(args.train_config, "r"), Loader=yaml.FullLoader)
    configs = (preprocess_config, model_config, train_config)

    # Control proportion of silences in function of duration coefficient
    if args.silence_control_bias:
        rounded_silence_proportion = round(18.98 * args.duration_control_bias - 12.01) # from GT distribution
        rounded_silence_proportion = min(rounded_silence_proportion, 100)
        rounded_silence_proportion = max(rounded_silence_proportion, 0)
        load_ablation = loadmat(model_config["bias_vector"]["ablation_silence_proportion"])
        args.pause_control_bias = load_ablation['ablation_silence_proportion'][rounded_silence_proportion]
        #print(args.pause_control_bias)

    # Control Bias array updated with args
    control_bias_array = model_config["bias_vector"]["value_by_param"].copy()
    if args.duration_control_bias != 1.0:
        control_bias_array[0] = args.duration_control_bias
    if args.pitch_control_bias != 0.0:
        control_bias_array[1] = args.pitch_control_bias
    if args.f1_control_bias != 0.0:
        control_bias_array[2] = args.f1_control_bias
    if args.f2_control_bias != 0.0:
        control_bias_array[3] = args.f2_control_bias
    if args.f3_control_bias != 0.0:
        control_bias_array[4] = args.f3_control_bias
    if args.spectral_tilt_control_bias != 0.0:
        control_bias_array[5] = args.spectral_tilt_control_bias
    if args.energy_control_bias != 0.0:
        control_bias_array[6] = args.energy_control_bias
    if args.relative_pos_control_bias != 0.0:
        control_bias_array[7] = args.relative_pos_control_bias
    if args.pfitzinger_control_bias != 0.0:
        control_bias_array[8] = args.pfitzinger_control_bias
    if args.cog_control_bias != 0.0:
        control_bias_array[9] = args.cog_control_bias
    if args.sb1k_control_bias != 0.0:
        control_bias_array[10] = args.sb1k_control_bias
        
    # Categorical Bias array updated with args
    categorical_control_bias_array = model_config["bias_vector"]["value_by_param_categorical"].copy()
    if args.pause_control_bias != 0.0:
        categorical_control_bias_array[0] = args.pause_control_bias
    if args.liaison_control_bias != 0.0:
        categorical_control_bias_array[1] = args.liaison_control_bias

    # Output of the model
    output_wav = train_config["output"]["wav"]

    # Get model
    model = get_model(args, configs, device, train=False, mode_batch=mode_batch)

    if output_wav:
        # Load vocoder
        vocoder = get_vocoder(model_config, device)
    else:
        vocoder = None

    # Preprocess texts
    if args.teacher_forcing == True:
        if args.mode == "batch":
            # Get dataset
            dataset = Dataset(
                # 'val_phon.txt', preprocess_config, train_config, sort=False, drop_last=False
                train_config["path"]["val_csv_path"], preprocess_config, train_config, sort=False, drop_last=False
            )
            batchs = DataLoader(
                dataset,
                batch_size=8,
                collate_fn=dataset.collate_fn,
            )
        else:
            print("Need to specify a batch to run teacher-forcing")
    else:
        if args.mode == "batch":
            # Get dataset
            dataset = TextDataset(args.source, preprocess_config, mode_batch=mode_batch)
            batchs = DataLoader(
                dataset,
                batch_size=8,
                collate_fn=dataset.collate_fn,
            )

    if args.mode == "single":
        ids = raw_texts = [args.text[:100]]
        speakers = np.array([args.speaker_id])
        if preprocess_config["preprocessing"]["text"]["language"] == "en":
            texts = np.array([preprocess_english(args.text, preprocess_config)])
        elif preprocess_config["preprocessing"]["text"]["language"] == "zh":
            texts = np.array([preprocess_mandarin(args.text, preprocess_config)])
        elif preprocess_config["preprocessing"]["text"]["language"] == "fr":
            texts = np.array([preprocess_french(args.text, preprocess_config)])
        text_lens = np.array([len(texts[0])])
        batchs = [(ids, raw_texts, speakers, texts, text_lens, max(text_lens))]

    control_values = args.pitch_control, args.energy_control, args.duration_control

    # control_bias_values = args.pitch_control_bias, args.energy_control_bias, args.duration_control_bias, args.spectral_tilt_control_bias, args.pause_control_bias, args.liaison_control_bias
    #categorical_control_bias_array = args.pause_control_bias, args.liaison_control_bias
    
    synthesize(
        model,
        args.restore_step, 
        configs, 
        vocoder, 
        batchs, 
        control_values, 
        args.teacher_forcing, 
        control_bias_array,
        categorical_control_bias_array,
        mode_batch=mode_batch,
    )
