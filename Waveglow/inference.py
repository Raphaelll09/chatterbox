# *****************************************************************************
#  Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#      * Redistributions of source code must retain the above copyright
#        notice, this list of conditions and the following disclaimer.
#      * Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
#      * Neither the name of the NVIDIA CORPORATION nor the
#        names of its contributors may be used to endorse or promote products
#        derived from this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
#  ARE DISCLAIMED. IN NO EVENT SHALL NVIDIA CORPORATION BE LIABLE FOR ANY
#  DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
#  (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
#  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
#  ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#  SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# *****************************************************************************
import os
from scipy.io.wavfile import write
import torch
from mel2samp import files_to_list, MAX_WAV_VALUE
from denoiser import Denoiser

import numpy as np


def main(mel_files, waveglow, sigma, output_dir, sampling_rate, is_fp16,
         denoiser_strength, factor_interp=1, gain=0, negative_gain=0):
    mel_files = files_to_list(mel_files)
    # waveglow = torch.load(waveglow_path, map_location=torch.device("cpu"))['model']
    # waveglow = waveglow.remove_weightnorm(waveglow)
    # # waveglow.cuda().eval()
    # waveglow.eval()
    if is_fp16:
        from apex import amp
        waveglow, _ = amp.initialize(waveglow, [], opt_level="O3")

    if denoiser_strength > 0:
        # denoiser = Denoiser(waveglow).cuda()
        denoiser = Denoiser(waveglow)

    for i, file_path in enumerate(mel_files):
        file_name = os.path.splitext(os.path.basename(file_path))[0]

        if True:
            # Processing for generic mel files
            shape = tuple(np.fromfile(file_path, count = 2, dtype = np.int32))
            mel = np.memmap(file_path,offset=8,dtype=np.float32,shape=shape)
            # mel = mel[2000:3000,:]
            mel = mel.transpose() + gain - negative_gain
            # print(type(mel[0,0]))
           
            mel = torch.from_numpy(mel)
            size_interp = round(mel.size(1)*factor_interp)
            mel_interp = np.zeros((mel.size(0), size_interp))
            for i in range(0,mel.size(0)):
                mel_interp[i] = np.interp(np.linspace(0, 1, size_interp), np.linspace(0, 1, mel.size(1)), mel[i])
            # mel_interp = mel_interp.astype(float)
            # mel = torch.from_numpy(mel)
            mel = torch.from_numpy(mel_interp)
            mel = mel.float()
        else:
            # mel = torch.load(file_path)
            mel = torch.from_numpy(np.load(file_path).transpose())

        # print(mel)
        # print(len(mel))
        # print(len(mel[0]))

        # mel = torch.autograd.Variable(mel.cuda())
        mel = torch.autograd.Variable(mel)
        mel = torch.unsqueeze(mel, 0)
        mel = mel.half() if is_fp16 else mel
        with torch.no_grad():
            audio = waveglow.infer(mel, sigma=sigma)
            if denoiser_strength > 0:
                audio = denoiser(audio, denoiser_strength)
            audio = audio * MAX_WAV_VALUE
        audio = audio.squeeze()
        audio = audio.cpu().numpy()
        audio = audio.astype('int16')
        audio_path = os.path.join(
            output_dir, "{}.wav".format(file_name))
        write(audio_path, sampling_rate, audio)
        print(audio_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-f', "--filelist_path", required=True)
    parser.add_argument('-w', '--waveglow_path',
                        help='Path to waveglow decoder checkpoint with model')
    parser.add_argument('-o', "--output_dir", required=True)
    parser.add_argument("-s", "--sigma", default=1.0, type=float)
    parser.add_argument("--sampling_rate", default=22050, type=int)
    parser.add_argument("--is_fp16", action="store_true")
    parser.add_argument("-d", "--denoiser_strength", default=0.0, type=float,
                        help='Removes model bias. Start with 0.1 and adjust')
    parser.add_argument("-sf", "--speed_factor", default=1, type=float,
                        help='Add a speed ratio to the synthesis')
    parser.add_argument("-g", "--gain", default=0, type=float,
                        help='Add a gain to mel-spectro (in dB)')
    parser.add_argument("-ng", "--negative_gain", default=0, type=float,
                        help='Add a negative gain to mel-spectro (in dB)')
    args = parser.parse_args()

    # load Waveglow model
    waveglow = torch.load(args.waveglow_path, map_location=torch.device("cpu"))['model']
    waveglow = waveglow.remove_weightnorm(waveglow)
    # waveglow.cuda().eval()
    waveglow.eval()

    main(args.filelist_path, waveglow, args.sigma, args.output_dir,
         args.sampling_rate, args.is_fp16, args.denoiser_strength, args.speed_factor, args.gain, args.negative_gain)
