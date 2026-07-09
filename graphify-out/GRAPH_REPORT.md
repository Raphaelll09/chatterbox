# Graph Report - embedded_tts  (2026-07-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 740 nodes · 1224 edges · 34 communities (30 shown, 4 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 211 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- modules.py
- tools.py
- LinearNorm
- train.py
- train
- Mel2Samp
- gui_utils.py
- test_audio_postprocess.py
- audio_postprocess.py
- __init__.py
- STFT
- Sampler
- MultiHeadAttention
- cleaners.py
- cleaners.py
- DynamicLossScaler
- train
- meldataset.py
- join.py
- .__init__
- AttrDict
- ScheduledOptim
- CMUDict
- Generator
- CMUDict
- __init__.py
- DistributedDataParallel
- inference.py
- convert_model.py
- symbols.py
- conftest.py
- symbols.py

## God Nodes (most connected - your core abstractions)
1. `EmbeddingBias` - 18 edges
2. `LinearNorm` - 15 edges
3. `train()` - 15 edges
4. `ConvNorm` - 14 edges
5. `Sampler` - 14 edges
6. `train()` - 13 edges
7. `FastSpeech2` - 12 edges
8. `EmbeddingBiasCategorical` - 12 edges
9. `text_to_sequence()` - 12 edges
10. `FFTBlock` - 12 edges

## Surprising Connections (you probably didn't know these)
- `ConvNorm` --uses--> `STFT`  [INFERRED]
  Waveglow/tacotron2/layers.py → FastSpeech2/audio/stft.py
- `LinearNorm` --uses--> `STFT`  [INFERRED]
  Waveglow/tacotron2/layers.py → FastSpeech2/audio/stft.py
- `TacotronSTFT` --uses--> `STFT`  [INFERRED]
  Waveglow/tacotron2/layers.py → FastSpeech2/audio/stft.py
- `vocoder_infer()` --calls--> `vocoder()`  [INFERRED]
  FastSpeech2/utils/model.py → synthesis_modules.py
- `train()` --calls--> `DistributedDataParallel`  [INFERRED]
  hifi-gan-master/train.py → Waveglow/tacotron2/distributed.py

## Import Cycles
- None detected.

## Communities (34 total, 4 thin omitted)

### Community 0 - "modules.py"
Cohesion: 0.05
Nodes (30): FastSpeech2, Conv, EmbeddingBias, EmbeddingBiasCategorical, get_sinusoid_encoding_table(), GST, LengthRegulator, LinearNorm (+22 more)

### Community 1 - "tools.py"
Cohesion: 0.06
Nodes (41): Dataset, load_FlauBERT_embedding_from_styleTag(), load_free_styleTags_embedding(), TextDataset, preprocess_english(), preprocess_french(), preprocess_mandarin(), process_per_batch() (+33 more)

### Community 2 - "LinearNorm"
Cohesion: 0.07
Nodes (23): ConvNorm, LinearNorm, Attention, Decoder, Encoder, LocationLayer, Postnet, Prenet (+15 more)

### Community 3 - "train.py"
Cohesion: 0.06
Nodes (28): SummaryWriter, 1) loads audio,text pairs         2) normalizes text and converts them to seque, Zero-pads model inputs and targets based on number of frames per setep, Collate's training batch from normalized text and mel-spectrogram         PARAM, TextMelCollate, TextMelLoader, apply_gradient_allreduce(), create_hparams() (+20 more)

### Community 4 - "train"
Cohesion: 0.06
Nodes (24): apply_gradient_allreduce(), _flatten_dense_tensors(), init_distributed(), Flatten dense tensors into a contiguous 1D buffer. Assume tensors are of     sa, View a flat buffer using the sizes of tensors. Assume that tensors are of     s, Modifies existing model to do gradient allreduce, but doesn't change class, reduce_tensor(), _unflatten_dense_tensors() (+16 more)

### Community 5 - "Mel2Samp"
Cohesion: 0.06
Nodes (22): Denoiser, Removes model bias from audio produced with waveglow, main(), files_to_list(), load_wav_to_torch(), Mel2Samp, Takes a text file of filenames and makes a list of filenames, Loads wavdata into torch array (+14 more)

### Community 6 - "gui_utils.py"
Cohesion: 0.09
Nodes (25): butter_lowpass_filter(), convert_seconds_to_datetime(), find_separators_subtitles(), findOccurrences(), play_audio(), Synthesize text with input text     Uses global variables set during models loa, syn_audio(), write_duration_alignements() (+17 more)

### Community 7 - "test_audio_postprocess.py"
Cohesion: 0.08
Nodes (14): ndarray, Pytest tests for audio_postprocess.py.  Covered scenarios ----------------- 1. 1, Sine at 3 dB crest is already below the 14 dB target; the limiter     should not, Constant signal: RMS == peak, crest == 0 dB., Pure sinusoid as float32., Speech-like signal: bandpass noise bursts + transient spikes.      Designed to h, _sine(), _speech_like() (+6 more)

### Community 8 - "audio_postprocess.py"
Cohesion: 0.14
Nodes (30): Any, analyze(), _apply_limiter(), _consecutive_runs(), _dbfs(), _frame_rms(), _from_float(), _linear() (+22 more)

### Community 9 - "__init__.py"
Cohesion: 0.08
Nodes (12): main(), read_pmic_power_w(), begin_sentence(), Start a new per-sentence recorder, or a no-op one when disabled., Publish the active recorder so nested calls (e.g. inside     synthesis_modules.s, Launch the background sampler as a subprocess. No-op if disabled or     not on L, set_current(), start_session() (+4 more)

### Community 10 - "STFT"
Cohesion: 0.11
Nodes (13): dynamic_range_compression(), dynamic_range_decompression(), griffin_lim(), # from librosa 0.6     Compute the sum-square envelope of a window function at, PARAMS     ------     magnitudes: spectrogram magnitudes     stft_fn: STFT cl, PARAMS     ------     C: compression factor, PARAMS     ------     C: compression factor used to compress, window_sumsquare() (+5 more)

### Community 11 - "Sampler"
Cohesion: 0.11
Nodes (12): cpu_percent(), parse_meminfo(), parse_pmic_power_w(), parse_proc_stat(), parse_throttled(), Parse /proc/stat content into {cpu_label: (jiffies...)}.      Only lines startin, Utilization % between two /proc/stat jiffie snapshots for one label.      prev/c, Return MemTotal - MemAvailable in MB, or None if fields are missing. (+4 more)

### Community 12 - "MultiHeadAttention"
Cohesion: 0.15
Nodes (9): ConvNorm, PostNet, PostNet: Five 1-d convolution with 512 channels and kernel size 5, Scaled Dot-Product Attention, ScaledDotProductAttention, MultiHeadAttention, PositionwiseFeedForward, A two-feed-forward-layer module (+1 more)

### Community 13 - "cleaners.py"
Cohesion: 0.17
Nodes (19): basic_cleaners(), collapse_whitespace(), convert_to_ascii(), english_cleaners(), expand_abbreviations(), expand_numbers(), lowercase(), from https://github.com/keithito/tacotron (+11 more)

### Community 14 - "cleaners.py"
Cohesion: 0.18
Nodes (19): basic_cleaners(), collapse_whitespace(), convert_to_ascii(), english_cleaners(), expand_abbreviations(), expand_numbers(), lowercase(), from https://github.com/keithito/tacotron (+11 more)

### Community 16 - "train"
Cohesion: 0.19
Nodes (8): discriminator_loss(), feature_loss(), generator_loss(), MultiPeriodDiscriminator, MultiScaleDiscriminator, train(), plot_spectrogram(), save_checkpoint()

### Community 17 - "meldataset.py"
Cohesion: 0.20
Nodes (8): dynamic_range_compression_torch(), dynamic_range_decompression_torch(), get_dataset_filelist(), load_wav(), mel_spectrogram(), MelDataset, spectral_de_normalize_torch(), spectral_normalize_torch()

### Community 18 - "join.py"
Cohesion: 0.31
Nodes (13): build_per_sentence_results(), build_per_stage_results(), _integrate_energy_j(), load_calibration(), load_samples(), load_sentences(), main(), Trapezoidal integral of pmic_power_w (W) over t_mono (s) -> Joules. (+5 more)

### Community 19 - ".__init__"
Cohesion: 0.19
Nodes (4): DiscriminatorP, DiscriminatorS, ResBlock2, get_padding()

### Community 20 - "AttrDict"
Cohesion: 0.26
Nodes (7): dict, AttrDict, build_env(), inference(), load_checkpoint(), main(), main()

### Community 21 - "ScheduledOptim"
Cohesion: 0.24
Nodes (3): Learning rate scheduling per step, A simple wrapper class for learning rate scheduling, ScheduledOptim

### Community 22 - "CMUDict"
Cohesion: 0.24
Nodes (6): CMUDict, _get_pronunciation(), _parse_cmudict(), from https://github.com/keithito/tacotron, Thin wrapper around CMUDict data. http://www.speech.cs.cmu.edu/cgi-bin/cmudict, Returns list of ARPAbet pronunciations of the given word.

### Community 23 - "Generator"
Cohesion: 0.24
Nodes (4): Generator, ResBlock1, init_weights(), load_hifigan()

### Community 24 - "CMUDict"
Cohesion: 0.24
Nodes (6): CMUDict, _get_pronunciation(), _parse_cmudict(), from https://github.com/keithito/tacotron, Thin wrapper around CMUDict data. http://www.speech.cs.cmu.edu/cgi-bin/cmudict, Returns list of ARPAbet pronunciations of the given word.

### Community 25 - "__init__.py"
Cohesion: 0.31
Nodes (9): _arpabet_to_sequence(), _clean_text(), from https://github.com/keithito/tacotron, Converts a string of text to a sequence of IDs corresponding to the symbols in t, Converts a sequence of IDs back to a string, sequence_to_text(), _should_keep_symbol(), _symbols_to_sequence() (+1 more)

### Community 26 - "DistributedDataParallel"
Cohesion: 0.22
Nodes (6): Module, DistributedDataParallel, _flatten_dense_tensors(), View a flat buffer using the sizes of tensors. Assume that tensors are of     s, Flatten dense tensors into a contiguous 1D buffer. Assume tensors are of     sa, _unflatten_dense_tensors()

### Community 27 - "inference.py"
Cohesion: 0.53
Nodes (4): get_mel(), inference(), load_checkpoint(), main()

### Community 28 - "convert_model.py"
Cohesion: 0.70
Nodes (4): _check_model_old_version(), update_model(), _update_model_cond(), _update_model_res_skip()

## Knowledge Gaps
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `train()` connect `train` to `train.py`, `meldataset.py`, `AttrDict`, `Generator`, `DistributedDataParallel`?**
  _High betweenness centrality (0.308) - this node is a cross-community bridge._
- **Why does `train()` connect `train` to `train.py`, `Mel2Samp`?**
  _High betweenness centrality (0.205) - this node is a cross-community bridge._
- **Why does `Generator` connect `Generator` to `train`, `inference.py`, `AttrDict`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `EmbeddingBias` (e.g. with `FastSpeech2` and `.__init__()`) actually correct?**
  _`EmbeddingBias` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `LinearNorm` (e.g. with `STFT` and `.__init__()`) actually correct?**
  _`LinearNorm` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `train()` (e.g. with `main()` and `get_dataset_filelist()`) actually correct?**
  _`train()` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `ConvNorm` (e.g. with `STFT` and `.__init__()`) actually correct?**
  _`ConvNorm` has 12 INFERRED edges - model-reasoned connections that need verification._