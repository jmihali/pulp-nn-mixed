#
# pulp_nn_factory.py
# Nazareno Bruschi <nazareno.bruschi@unibo.it>
#
# Copyright (C) 2019-2020 University of Bologna
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import errno
import os
import imp, sys
import shutil
import torch
import torch.nn as nn
import numpy as np
import random
from mako.template import Template
from models.linear_quantized_modules import ClippedLinearQuantization, LearnedClippedLinearQuantization, ScaledClippedLinearQuantization,\
        ScaledThresholdsQuantization4d
from include.pulp_nn_struct import PULPNNSrcDirsSW32bit, PULPNNSrcDirsSW64bit, PULPNNSrcDirsHW32bit, PULPNNSrcDirsHW64bit, PULPNNSrcDirsExtHW32bit, PULPNNSrcDirsExtHW64bit,\
        PULPNNInstallPathSW32bit, PULPNNInstallPathSW64bit, PULPNNInstallPathHW32bit, PULPNNInstallPathHW64bit, PULPNNInstallSWPath, PULPNNInstallHWPath, PULPNNInstallExtHWPath,\
        PULPNNInstallPathExtHW32bit, PULPNNInstallPathHW64bit

##################################################################################### PULP-NN Factory ############################################################

def sgn_str(s : bool):
    return 'i' if s else 'u'

class PULPNNKernel(object):
    def __init__(self, name, inp, out, wt, quant, act_prec, ext, mm_fmt, in_signed=False, out_signed=False):
        self.type = name
        self.in_data_t = inp
        self.out_data_t = out
        self.wt_data_t = wt
        self.quantization = quant
        self.act_prec = act_prec
        self.extentions = ext
        self.matmul_fmt = mm_fmt
        self.in_signed = in_signed
        self.out_signed = out_signed

class PULPNNLayer(object):
    def __init__(self, dim_in_x, dim_in_y, ch_in, ch_out, dim_out_x,
                    dim_out_y, ker_x, ker_y, stride_x, stride_y, pad_y_top,
                    pad_y_bot, pad_x_left, pad_x_right, pool_kernel, pool_stride,
                    bias=False, bn=True, relu=True):
        self.dim_in_x = dim_in_x
        self.dim_in_y = dim_in_y
        self.ch_in = ch_in
        self.ch_out = ch_out
        self.dim_out_x = dim_out_x
        self.dim_out_y = dim_out_y
        self.ker_x = ker_x
        self.ker_y = ker_y
        self.stride_x = stride_x
        self.stride_y = stride_y
        self.pad_y_top = pad_y_top
        self.pad_y_bot = pad_y_bot
        self.pad_x_left = pad_x_left
        self.pad_x_right = pad_x_right
        self.pool_kernel = pool_kernel
        self.pool_stride = pool_stride
        self.bias = bias
        self.bn = bn
        self.relu = relu

class PULPNNFactory(object):
    def __init__(self, kernel, layer):
        self.kernel = kernel
        self.layer = layer
        self.fn_name = ''
        self.filename = ''
        self.api = ''

    def generate_api(self):
        return Template(filename="templates/pulp_nn_api.t", strict_undefined=True).render(config=self)

    def generate_make(self):
        return Template(filename="templates/pulp_nn_make.t", strict_undefined=True).render(config=self)

    def generate_call(self):
        return Template(filename="templates/pulp_nn_call.t", strict_undefined=True).render(config=self)

    def generate_include(self):
        return Template(filename="templates/pulp_nn_include.t", strict_undefined=True).render(config=self)

class PULPNNDataAllocation(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.fn_name = "data_allocation{0}{1}{2}".format("_" + sgn_str(self.kernel.in_signed) + str(self.kernel.in_data_t) if self.kernel.in_data_t != None else "",
                                                         "_" + sgn_str(self.kernel.out_signed) + str(self.kernel.out_data_t) if self.kernel.out_data_t != None else "",
                                                         "_" + str(self.kernel.wt_data_t) if self.kernel.wt_data_t != None else "")
        self.filename = self.fn_name + ".h"
        self.api = self.__class__.__name__
        self.less_precision = min([self.kernel.in_data_t if self.kernel.in_data_t != None else 255, self.kernel.wt_data_t if self.kernel.wt_data_t != None else 255, self.kernel.out_data_t if self.kernel.out_data_t != None else 255])

    def generate_code(self):
        return Template(filename="templates/data_allocation_x_y_z.t", strict_undefined=True).render(config=self)

def iu(sgn):
    return 'i' if sgn else 'u'

class PULPNNGoldenModel(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.fn_name = "golden{0}{1}{2}".format("_" + iu(self.kernel.in_signed) + str(self.kernel.in_data_t) if self.kernel.in_data_t != None else "",
                                                "_" + iu(self.kernel.out_signed) + str(self.kernel.out_data_t) if self.kernel.out_data_t != None else "",
                                                "_" + str(self.kernel.wt_data_t) if self.kernel.wt_data_t != None else "")
        self.filename = self.fn_name + ".h"
        self.api = self.__class__.__name__

    def generate_code(self):
        if self.kernel.type == 'matmul':
            self.golden = matmul_mixed_tests_generator(self.layer, self.kernel)
        elif self.kernel.type == 'convolution' or self.kernel.type == 'pointwise' or self.kernel.type == 'depthwise':
            self.golden = convolution_mixed_tests_generator(self.layer, self.kernel)
        elif self.kernel.type == 'linear_no_quant' or self.kernel.type == 'linear_quant':
            self.golden = linear_mixed_tests_generator(self.layer, self.kernel)
        elif self.kernel.type == 'maxpool' or self.kernel.type == 'avgpool':
            self.golden = pooling_mixed_tests_generator(self.layer, self.kernel)
        elif self.kernel.type == 'add':
            self.golden = add_mixed_tests_generator(self.layer, self.kernel)
        return Template(filename="templates/golden_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNMakefile(PULPNNFactory):
    def __init__(self, kernel):
        super().__init__(kernel, None)
        self.fn_name = "Makefile"
        self.filename = self.fn_name

    def generate_code(self, make):
        self.make = make
        return Template(filename="templates/make.t", strict_undefined=True).render(config=self)

class PULPNNTest(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.fn_name = "test"
        self.filename = self.fn_name + ".c"

    def generate_code(self, include, call):
        self.include = include
        self.call = call
        return Template(filename="templates/test.t", strict_undefined=True).render(config=self)

class PULPNNUtils(PULPNNFactory):
    def __init__(self):
        super().__init__(None, None)
        self.fn_name = "pulp_nn_utils"
        self.filename_c = self.fn_name + ".c"
        self.filename_h = self.fn_name + ".h"

    def generate_code(self, act_prec):
        self.act_prec=act_prec
        return Template(filename="templates/pulp_nn_utils_c.t", strict_undefined=True).render(config=self)

    def generate_header(self, act_prec):
        self.act_prec=act_prec
        return Template(filename="templates/pulp_nn_utils_h.t", strict_undefined=True).render(config=self)


class PULPNNConvolve(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_conv_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                                                                       str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""), sgn_str(kernel.in_signed), sgn_str(kernel.out_signed))
            self.im2col_fn = "pulp_nn_im2col_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), '8', sgn_str(kernel.in_signed))
            self.mat_mul_fn = "pulp_nn_matmul_{3}8_{4}{0}_i{1}{2}".format(str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                                                                          str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""), sgn_str(kernel.in_signed), sgn_str(kernel.out_signed))
            self.unpack_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
        elif self.kernel.extentions == 'XpulpNN':
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.fn_name = "xpulp_nn_conv_{5}{0}_{6}{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                           str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""),
                                                                           sgn_str(kernel.in_signed),
                                                                           sgn_str(kernel.out_signed))
            self.zeromem_fn = "xpulp_nn_zero_mem_u{0}".format(str(self.max_precision))
            self.im2col_fn = "xpulp_nn_im2col_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), str(self.max_precision),
                                                                       sgn_str(kernel.in_signed))
            self.mat_mul_fn = "xpulp_nn_matmul_{5}{0}_{6}{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                                                                                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                                str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""),
                                                                                sgn_str(kernel.in_signed),
                                                                                sgn_str(kernel.out_signed))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.fn_name = "xpulp_nn_mix_conv_u{0}_u{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""))
            self.zeromem_fn = "xpulp_nn_zero_mem_u{0}".format(str(self.max_precision))
            self.im2col_fn = "xpulp_nn_im2col_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), str(self.max_precision),
                                                                       sgn_str(kernel.in_signed))
            self.mat_mul_fn = "xpulp_nn_mix_matmul_u{0}_u{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.bn_fn = "pulp_nn_bn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.relu_fn = "pulp_nn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t)
                                                     )
        self.thr_fn = None

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_conv_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_conv_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_mix_conv_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNConvolvePointwise(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)

        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_pointwise_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                                                                            str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                            sgn_str(kernel.in_signed),
                                                                            sgn_str(kernel.out_signed))
            self.im2col_fn = "pulp_nn_im2col_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t), '8',
                                                                      sgn_str(kernel.in_signed))
            self.mat_mul_fn = "pulp_nn_matmul_{3}8_{4}{0}_i{1}{2}".format(str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                                                                          str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                          sgn_str(kernel.in_signed),
                                                                          sgn_str(kernel.out_signed))
            self.unpack_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
        # TODO: add pointwise mixed kernels
        elif self.kernel.extentions in ['XpulpNN', 'XpulpNN-mixed']:
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.fn_name = "xpulp_nn_pointwise_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t),
                                                                             str(self.kernel.out_data_t),
                                                                             str(self.kernel.wt_data_t),
                                                                             str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                             sgn_str(kernel.in_signed),
                                                                             sgn_str(kernel.out_signed))
            self.im2col_fn = "xpulp_nn_im2col_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                       str(self.max_precision),
                                                                       sgn_str(kernel.in_signed))
            self.mat_mul_fn = "xpulp_nn_matmul_{5}{0}_{6}{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t),
                                                                                str(self.kernel.out_data_t),
                                                                                str(self.kernel.wt_data_t),
                                                                                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                                str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""),
                                                                                sgn_str(kernel.in_signed),
                                                                                sgn_str(kernel.out_signed))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  '8',
                                                                  sgn_str(kernel.in_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
        #elif self.kernel.extentions == 'XpulpNN-mixed':
        #    self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
        #    self.fn_name = "xpulp_nn_mix_pointwise_u{0}_u{1}_i{2}{3}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
        #        str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""))#,
        #        #str("_" + self.kernel.matmul_fmt if self.matmul_fmt == '4x4' else ""))
        #    self.im2col_fn = "xpulp_nn_im2col_u{0}_to_u{1}".format(str(self.kernel.in_data_t), str(self.max_precision))
        #    self.mat_mul_fn = "xpulp_nn_mix_matmul_u{0}_u{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
        #        str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
        #        str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""))
        #    self.unpack_in_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.in_data_t), '8')
        #    self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.bn_fn = "pulp_nn_bn_quant_{0}{1}".format(sgn_str(kernel.out_signed),
                                                      str(self.kernel.out_data_t))
        self.relu_fn = "pulp_nn_quant_{0}{1}".format(sgn_str(kernel.out_signed),
                                                     str(self.kernel.out_data_t))
        self.thr_fn = None

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_pointwise_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_pointwise_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_mix_pointwise_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNConvolveDepthwise(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_depthwise_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t),
                                                                            str(self.kernel.out_data_t),
                                                                            str(self.kernel.wt_data_t),
                                                                            str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                            sgn_str(kernel.in_signed),
                                                                            sgn_str(kernel.out_signed))
        elif self.kernel.extentions == 'XpulpNN':
            self.fn_name = "xpulp_nn_depthwise_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t),
                                                                             str(self.kernel.out_data_t),
                                                                             str(self.kernel.wt_data_t),
                                                                             str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                            sgn_str(kernel.in_signed),
                                                                            sgn_str(kernel.out_signed))
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.fn_name = "xpulp_nn_depthwise_{4}{0}_{5}{1}_i{2}{3}".format(str(self.kernel.in_data_t),
                                                                             str(self.kernel.out_data_t),
                                                                             str(self.kernel.wt_data_t),
                                                                             str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                            sgn_str(kernel.in_signed),
                                                                            sgn_str(kernel.out_signed))
        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.bn_fn = "pulp_nn_bn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.relu_fn = "pulp_nn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.thr_fn = None
        self.less_precision = min([self.kernel.in_data_t, self.kernel.wt_data_t, self.kernel.out_data_t])

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_dw_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_dw_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_dw_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNMatMul(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)

        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_matmul_{3}8_{4}{0}_i{1}{2}".format(str(self.kernel.out_data_t),
                                                                       str(self.kernel.wt_data_t),

                                                                       str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                       sgn_str(kernel.in_signed),
                                                                       sgn_str(kernel.out_signed))
            self.unpack_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
        elif self.kernel.extentions == 'XpulpNN':
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.fn_name = "xpulp_nn_matmul_{5}{0}_{6}{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t),
                                                                             str(self.kernel.out_data_t),
                                                                             str(self.kernel.wt_data_t),
                                                                             str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                                                                             str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""),
                                                                             sgn_str(kernel.in_signed),
                                                                             sgn_str(kernel.out_signed))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
            #TODO: signed mix-matmul
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.fn_name = "xpulp_nn_mix_matmul_u{0}_u{1}_i{2}{3}{4}".format(str(self.kernel.in_data_t), str(self.kernel.out_data_t), str(self.kernel.wt_data_t),
                str("_" + self.kernel.quantization if self.kernel.quantization != "shift_clip" else ""),
                str("_" + self.kernel.matmul_fmt if self.kernel.matmul_fmt == '4x4' else ""))
            self.unpack_in_fn = "pulp_nn_u{0}_to_u{1}".format(str(self.kernel.in_data_t), str(self.max_precision))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.bn_fn = "pulp_nn_bn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.thr_fn = None
        self.relu_fn = "pulp_nn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_matmul_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_matmul_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_mix_matmul_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNLinearNoQuant(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)

        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_linear_{3}{0}_i{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                    '32',
                                                                    str(self.kernel.wt_data_t),
                                                                    sgn_str(self.kernel.in_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  '8',
                                                                  sgn_str(kernel.in_signed))
        elif self.kernel.extentions == 'XpulpNN':
            self.fn_name = "xpulp_nn_linear_{3}{0}_i{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                     '32',
                                                                     str(self.kernel.wt_data_t),
                                                                     sgn_str(kernel.in_signed))
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.fn_name = "xpulp_nn_linear_{3}{0}_i{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                     '32',
                                                                     str(self.kernel.wt_data_t),
                                                                     sgn_str(kernel.in_signed))
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.less_precision = min([self.kernel.in_data_t, self.kernel.wt_data_t])

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_linear_nq_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_linear_nq_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_linear_nq_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNLinearQuant(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)

        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_linear_{3}{0}_{4}{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                      str(self.kernel.out_data_t),
                                                                      str(self.kernel.wt_data_t),
                                                                      sgn_str(kernel.in_signed),
                                                                      sgn_str(kernel.out_signed))
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), '8')
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  '8',
                                                                  sgn_str(kernel.in_signed))
        elif self.kernel.extentions == 'XpulpNN':
            self.fn_name = "xpulp_nn_linear_{3}{0}_{4}{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                       str(self.kernel.out_data_t),
                                                                       str(self.kernel.wt_data_t),
                                                                       sgn_str(kernel.in_signed),
                                                                       sgn_str(kernel.out_signed))
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.fn_name = "xpulp_nn_linear_{3}{0}_{4}{1}_i{2}".format(str(self.kernel.in_data_t),
                                                                       str(self.kernel.out_data_t),
                                                                       str(self.kernel.wt_data_t),
                                                                       sgn_str(kernel.in_signed),
                                                                       sgn_str(kernel.out_signed))
            self.max_precision = max([self.kernel.in_data_t, self.kernel.wt_data_t])
            self.unpack_wt_fn = "pulp_nn_i{0}_to_i{1}".format(str(self.kernel.wt_data_t), str(self.max_precision))
            self.unpack_in_fn = "pulp_nn_{2}{0}_to_{2}{1}".format(str(self.kernel.in_data_t),
                                                                  str(self.max_precision),
                                                                  sgn_str(kernel.in_signed))

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.bn_fn = "pulp_nn_bn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.relu_fn = "pulp_nn_quant_{0}{1}".format(sgn_str(kernel.out_signed), str(self.kernel.out_data_t))
        self.thr_fn = None
        self.less_precision = min([self.kernel.in_data_t, self.kernel.wt_data_t])

    def generate_code(self):
        if self.kernel.extentions == 'XpulpV2':
            return Template(filename="templates/pulp_nn_linear_q_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN':
            return Template(filename="templates/XpulpNN/xpulp_nn_linear_q_x_y_z.t", strict_undefined=True).render(config=self)
        elif self.kernel.extentions == 'XpulpNN-mixed':
            return Template(filename="templates/XpulpNN-mixed/xpulp_nn_linear_q_x_y_z.t", strict_undefined=True).render(config=self)

class PULPNNMaxPool(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)

        if self.kernel.extentions == 'XpulpV2':
            self.fn_name = "pulp_nn_maxpool_{0}{1}".format(sgn_str(kernel.in_signed),
                                                           str(self.kernel.in_data_t))
            self.comp_and_replace_fn = "pulp_nn_compare_and_replace_if_larger_{0}{1}".format(sgn_str(kernel.in_signed),
                                                                                             str(self.kernel.in_data_t))
        elif self.kernel.extentions == 'XpulpNN':
            self.fn_name = "xpulp_nn_maxpool_{0}{1}".format(sgn_str(kernel.in_signed),
                                                            str(self.kernel.in_data_t))
            self.comp_and_replace_fn = "xpulp_nn_compare_and_replace_if_larger_{0}{1}".format(sgn_str(kernel.in_signed),
                                                                                              str(self.kernel.in_data_t))
            # there is no 'xpulp_nn_compare_and_replace_if_larger_u8'
            if self.kernel.in_data_t == 8:
                self.comp_and_replace_fn = self.comp_and_replace_fn[1:]
        elif self.kernel.extentions == 'XpulpNN-mixed':
            self.fn_name = "xpulp_nn_maxpool_{0}{1}".format(sgn_str(kernel.in_signed),
                                                            str(self.kernel.in_data_t))
            self.comp_and_replace_fn = "xpulp_nn_compare_and_replace_if_larger_{0}{1}".format(sgn_str(kernel.in_signed),
                                                                                              str(self.kernel.in_data_t))
            # there is no 'xpulp_nn_compare_and_replace_if_larger_{u/i}8'
            if self.kernel.in_data_t == 8:
                self.comp_and_replace_fn = self.comp_and_replace_fn[1:]

        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__

    def generate_code(self):
        return Template(filename="templates/pulp_nn_maxpool_x.t", strict_undefined=True).render(config=self)

class PULPNNAvgPoolNew(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.fn_name = "pulp_nn_avgpool_{}{}_{}{}".format(sgn_str(kernel.in_signed),
                                                          str(self.kernel.in_data_t),
                                                          sgn_str(kernel.out_signed),
                                                          str(self.kernel.out_data_t))
        if 'XpulpNN' in self.kernel.extentions:
            self.fn_name = "x"+self.fn_name
        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__

    def generate_code(self):
        return Template(filename="templates/pulp_nn_avgpool_new.t", strict_undefined=True).render(config=self)


class PULPNNAdd(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.in1_data_t = kernel.in_data_t
        self.in2_data_t = kernel.out_data_t
        self.fn_name = "pulp_nn_add_u{0}_u{1}".format(str(self.in1_data_t), str(self.in2_data_t))
        if "XpulpNN" in self.kernel.extentions:
            self.fn_name = "x" + self.fn_name
        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.unpack_in1_fn = "pulp_nn_u{0}_to_u{1}_r".format(str(self.in1_data_t), '8')
        self.unpack_in2_fn = "pulp_nn_u{0}_to_u{1}_r".format(str(self.in2_data_t), '8')
        self.max_precision = max([self.in1_data_t, self.in2_data_t])
        self.add_fn = "pulp_nn_add_quant_u{0}".format(str(self.max_precision))

    def generate_code(self):
        return Template(filename="templates/pulp_nn_add_x_y.t", strict_undefined=True).render(config=self)


class PULPNNQuantAdd(PULPNNFactory):
    def __init__(self, kernel, layer):
        super().__init__(kernel, layer)
        self.in1_data_t = kernel.in_data_t[0]
        self.in2_data_t = kernel.in_data_t[1]
        self.in1_signed = kernel.in_signed[0]
        self.in2_signed = kernel.in_signed[1]
        self.out_data_t = kernel.out_data_t
        self.fn_name = "pulp_nn_add_{0}{1}_{2}{3}_{4}{5}".format(sgn_str(kernel.in_signed[0]),
                                                                 str(self.in1_data_t),
                                                                 sgn_str(kernel.in_signed[1]),
                                                                 str(self.in2_data_t),
                                                                 sgn_str(kernel.out_signed),
                                                                 str(self.out_data_t))
        if "XpulpNN" in self.kernel.extentions:
            self.fn_name = "x" + self.fn_name
        self.filename = self.fn_name + ".c"
        self.api = self.__class__.__name__
        self.unpack_in1_fn = "pulp_nn_{0}{1}_to_{0}8_r".format(sgn_str(kernel.in_signed[0]),
                                                               str(self.in1_data_t))
        self.unpack_in2_fn = "pulp_nn_{0}{1}_to_{0}8_r".format(sgn_str(kernel.in_signed[1]),
                                                               str(self.in2_data_t))
        self.max_precision = max([self.in1_data_t, self.in2_data_t])

    def generate_code(self):
        return Template(filename="templates/pulp_nn_add_ql_x_y_z.t", strict_undefined=True).render(config=self)

###################################################################################### Model Factory ################################################

class PULPNNBatchNorm(nn.Module):
    def __init__(self, Cin=8, Kh=3, Kw=3, BitA=8, BitW=8, BitO=8, groups=1, inplace=True, SgnO=False):
        super(PULPNNBatchNorm, self).__init__()
        torch.manual_seed(5)
        random.seed(5)
        self.BitO = BitO
        self.k = torch.Tensor(1, Cin, 1, 1).uniform_(0, (2**(8)))
        self.k = torch.round(self.k)
        th = int(
            (2**(BitA + BitW + np.log2(int(Cin / groups) * Kh * Kw) + 4 - 2 - 1)))
        if th > 2**24:
            th = 2**24
        self.l = torch.Tensor(1, Cin, 1, 1).random_(-th, th)
        self.d = torch.Tensor(1).fill_(
            int(BitA + BitW + np.log2(int(Cin / groups) * Kh * Kw) + 3 - BitO))

        self.SgnO = SgnO

    def forward(self, input):
        output = input * self.k + self.l
        x = torch.floor(output >> self.d)
        out = clip8(x, self.BitO, self.SgnO)
        return out

class PULPNN1DBatchNorm(nn.Module):
    def __init__(self, Cin=8, BitA=8, BitW=8, BitO=8, groups=1, inplace=True, SgnO=False):
        super(PULPNN1DBatchNorm, self).__init__()
        self.BitO = BitO
        self.k = torch.Tensor(1, Cin).uniform_(-(2**8), (2**(8)))
        self.k = torch.round(self.k)
        th = int(
            (2**(BitA + BitW + np.log2(int(Cin / groups)) + 4 - 2 - 1)))
        if th > 2**30:
            th = 2**30
        self.l = torch.Tensor(1, Cin).random_(-th, th)
        self.d = torch.Tensor(1).fill_(
            int(BitA + BitW + np.log2(int(Cin / groups)) + 3 - BitO))
        self.SgnO = SgnO

    def forward(self, input):
        output = input * self.k + self.l
        x = torch.floor(output >> self.d)
        out = clip8(x, self.BitO, self.SgnO)
        return out

class PULPNNReLu(nn.Module):
    def __init__(self, BitO=8, SgnO=False):
        super(PULPNNReLu, self).__init__()
        self.out_mult = None
        self.out_shift = None
        self.BitO = BitO
        self.SgnO = SgnO

    def forward(self, input):
        output = torch.floor((input * self.out_mult) >> self.out_shift)
        out = clip8(output, self.BitO, self.SgnO)
        return out

class PULPNNShiftClip(nn.Module):
    def __init__(self, out_shift=None, BitI=8, BitW=8, BitO=8, SgnO=False):
        super(PULPNNShiftClip, self).__init__()
        self.BitO = BitO
        if out_shift == None:
            self.out_shift = torch.Tensor([max(self.BitO - max((BitI - BitW), (BitW - BitI)), max((BitI - BitW), (BitW - BitI)) - self.BitO)])
        else:
            self.out_shift = torch.Tensor([out_shift])
        self.SgnO = SgnO

    def forward(self, input):
        output = torch.floor(input >> self.out_shift)
        out = clip8(output, self.BitO, self.SgnO)
        return out

def headers(act_prec='32bit', ext='XpulpV2'):
    if ext == 'XpulpV2':
        if act_prec == '32bit':
            shutil.copyfile(PULPNNSrcDirsSW32bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsSW32bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsSW32bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsSW32bit['pulp_nn_include'] + "pulp_nn_utils.h")
        elif act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsSW64bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsSW64bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsSW64bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsSW64bit['pulp_nn_include'] + "pulp_nn_utils.h")
    elif ext == 'XpulpNN':
        if act_prec == '32bit':
            shutil.copyfile(PULPNNSrcDirsHW32bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsHW32bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsHW32bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsHW32bit['pulp_nn_include'] + "pulp_nn_utils.h")
        elif act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsHW64bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsHW64bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsHW64bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsHW64bit['pulp_nn_include'] + "pulp_nn_utils.h")
    elif ext == 'XpulpNN-mixed':
        if act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsExtHW32bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsExtHW32bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsExtHW32bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsExtHW32bit['pulp_nn_include'] + "pulp_nn_utils.h")
        elif act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsExtHW64bit['inc'] + "pulp_nn_kernels.h", PULPNNSrcDirsExtHW64bit['pulp_nn_include'] + "pulp_nn_kernels.h")
            shutil.copyfile(PULPNNSrcDirsExtHW64bit['inc'] + "pulp_nn_utils.h", PULPNNSrcDirsExtHW64bit['pulp_nn_include'] + "pulp_nn_utils.h")

def copy_file(src_tag, key, dest_tag):
    if key.kernel.extentions == 'XpulpV2':
        if key.kernel.act_prec == '32bit':
            shutil.copyfile(PULPNNSrcDirsSW32bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsSW32bit[dest_tag] + "%s" % key.filename)
        elif key.kernel.act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsSW64bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsSW64bit[dest_tag] + "%s" % key.filename)
    elif key.kernel.extentions == 'XpulpNN':
        if key.kernel.act_prec == '32bit':
            shutil.copyfile(PULPNNSrcDirsHW32bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsHW32bit[dest_tag] + "%s" % key.filename)
        elif key.kernel.act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsHW64bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsHW64bit[dest_tag] + "%s" % key.filename)
    elif key.kernel.extentions == 'XpulpNN-mixed':
        if key.kernel.act_prec == '32bit':
            shutil.copyfile(PULPNNSrcDirsExtHW32bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsExtHW32bit[dest_tag] + "%s" % key.filename)
        elif key.kernel.act_prec == '64bit':
            shutil.copyfile(PULPNNSrcDirsExtHW64bit[src_tag] + "%s" % key.filename, PULPNNSrcDirsExtHW64bit[dest_tag] + "%s" % key.filename)

def header(act_prec, ext, api):
    if ext == 'XpulpV2':
        if act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit['inc'] + "/pulp_nn_kernels.h", 'w')
        elif act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit['inc'] + "/pulp_nn_kernels.h", 'w')
    elif ext == 'XpulpNN':
        if act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit['inc'] + "/pulp_nn_kernels.h", 'w')
        elif act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit['inc'] + "/pulp_nn_kernels.h", 'w')
    elif ext == 'XpulpNN-mixed':
        if act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit['inc'] + "/pulp_nn_kernels.h", 'w')
        elif act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit['inc'] + "/pulp_nn_kernels.h", 'w')
    new_file.write(Template(filename="templates/pulp_nn_kernels.t", strict_undefined=True).render(PULPNNAPI=api, PULPNNEXT=ext))
    new_file.close()

def utils(act_prec, ext):
    comp = PULPNNUtils()
    if ext == 'XpulpV2':
        if act_prec == '32bit':
            new_file_h = open(PULPNNSrcDirsSW32bit['inc'] + comp.filename_h, 'w')
        elif act_prec == '64bit':
            new_file_h = open(PULPNNSrcDirsSW64bit['inc'] + comp.filename_h, 'w')
    elif ext == 'XpulpNN':
        if act_prec == '32bit':
            new_file_h = open(PULPNNSrcDirsHW32bit['inc'] + comp.filename_h, 'w')
        elif act_prec == '64bit':
            new_file_h = open(PULPNNSrcDirsHW64bit['inc'] + comp.filename_h, 'w')
    elif ext == 'XpulpNN-mixed':
        if act_prec == '32bit':
            new_file_h = open(PULPNNSrcDirsExtHW32bit['inc'] + comp.filename_h, 'w')
        elif act_prec == '64bit':
            new_file_h = open(PULPNNSrcDirsExtHW64bit['inc'] + comp.filename_h, 'w')
    new_file_h.write(comp.generate_header(act_prec))
    new_file_h.close()

def kernel(path_tag, comp, api):
    api += comp.generate_api() + "\n"
    if comp.kernel.extentions == 'XpulpV2':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit[path_tag] + comp.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit[path_tag] + comp.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit[path_tag] + comp.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit[path_tag] + comp.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN-mixed':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit[path_tag] + comp.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit[path_tag] + comp.filename, 'w')
    new_file.write(comp.generate_code())
    new_file.close()

    return api

def generation(call, make, include, comp):
    if call != None:
        call += comp.generate_call() + "\n"
    make += comp.generate_make() + "\n"
    if include != None:
        include += comp.generate_include() + "\n"

    return call,make,include

def allocation(path_tag, comp):
    c = PULPNNDataAllocation(kernel=comp.kernel, layer=comp.layer)
    if comp.kernel.extentions == 'XpulpV2':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit[path_tag] + c.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit[path_tag] + c.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN-mixed':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit[path_tag] + c.filename, 'w')
    new_file.write(c.generate_code())
    new_file.close()

def golden(path_tag, comp):
    c = PULPNNGoldenModel(kernel=comp.kernel, layer=comp.layer)
    if comp.kernel.extentions == 'XpulpV2':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit[path_tag] + c.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit[path_tag] + c.filename, 'w')
    elif comp.kernel.extentions == 'XpulpNN-mixed':
        if comp.kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit[path_tag] + c.filename, 'w')
        elif comp.kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit[path_tag] + c.filename, 'w')
    new_file.write(c.generate_code())
    new_file.close()

def makefile(path_tag, make, kernel):
    c = PULPNNMakefile(kernel=kernel)
    if kernel.extentions == 'XpulpV2':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit[path_tag] + c.filename, 'w')
    elif kernel.extentions == 'XpulpNN':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit[path_tag] + c.filename, 'w')
    elif kernel.extentions == 'XpulpNN-mixed':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit[path_tag] + c.filename, 'w')
    new_file.write(c.generate_code(make=make))
    new_file.close()

def test(path_tag, include, call, layer, kernel):
    c = PULPNNTest(kernel=kernel, layer=layer)
    if kernel.extentions == 'XpulpV2':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsSW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsSW64bit[path_tag] + c.filename, 'w')
    elif kernel.extentions == 'XpulpNN':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsHW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsHW64bit[path_tag] + c.filename, 'w')
    elif kernel.extentions == 'XpulpNN-mixed':
        if kernel.act_prec == '32bit':
            new_file = open(PULPNNSrcDirsExtHW32bit[path_tag] + c.filename, 'w')
        elif kernel.act_prec == '64bit':
            new_file = open(PULPNNSrcDirsExtHW64bit[path_tag] + c.filename, 'w')
    new_file.write(c.generate_code(include=include, call=call))
    new_file.close()

# Define string returning function for input-output-weights-thresholds
def str_tensor(x, tensor_name):
    input_image_txt = '#define '+tensor_name+' {'
    in_ch,H,W = x.size(1), x.size(2), x.size(3)
    for i in range(H):
        for j in range(W):
            for c in range(in_ch):
                input_image_txt += str(int(x[0][c][i][j].item())) + ', '
        input_image_txt+='\\\n'
    input_image_txt = input_image_txt[:-4]+'}\n'
    return input_image_txt

def str_weight(weight, tensor_name):
    out_ch, in_ch, k_w  = weight.size(0), weight.size(1), weight.size(2)
    str_v = '#define '+tensor_name+' {'
    for v in range(out_ch):
        for i in range(k_w):
            for j in range(k_w):
                for k in range(in_ch):
                    str_v += str(int(weight[v][k][i][j].item())) + ', '
        str_v += '\\\n'
    str_v = str_v[:-4]+'}\n'
    return str_v

def str_thr(thr, tensor_name):
    out_ch, thr_dim  = thr.size(0), thr.size(1)
    str_v = '#define '+tensor_name+' {'
    for v in range(out_ch):
        for i in range(thr_dim+1):
            if i == thr_dim:
                str_v += str(int(0)) + ', '
            else:
                str_v += str(int(thr[v][i].item())) + ', '

        str_v += '\\\n'
    str_v = str_v[:-4]+'}\n'
    return str_v

# To convert in HWC format the weights
def HWC_weights(w, nof, fs, nif):
    weights=np.zeros((nof, fs, fs, nif), 'int8')
    for i in range(nof):
        for j in range(fs):
            for k in range(fs):
                for t in range(nif):
                    weights[i,j,k,t]= (w[i,t,j,k])
    return weights

def str_weight_8(weight, tensor_name):
    out_ch, k_w, k_w2, in_ch  = weight.shape
    str_v = '#define '+tensor_name+' {'
    for v in range(out_ch):
        for i in range(k_w):
            for j in range(k_w):
                for k in range(in_ch):
                    str_v += str(int(weight[v][i][j][k].item())) + ', '
        str_v += '\\\n'
    str_v = str_v[:-4]+'}\n'
    return str_v

def str_tensor_8(x, tensor_name):
    input_image_txt = '#define '+tensor_name+' {'
    H,W, in_ch = x.shape
    for i in range(H):
        for j in range(W):
            for c in range(in_ch):
                input_image_txt += str(int(x[i][j][c].item())) + ', '
        input_image_txt+='\\\n'
    input_image_txt = input_image_txt[:-4]+'}\n'
    return input_image_txt

def str_tensor_linear(x, tensor_name):
    input_image_txt = '#define '+tensor_name+' {'
    in_ch = x.size(1)
    for c in range(in_ch):
        input_image_txt += str(int(x[0][c].item())) + ', '
    input_image_txt+='\\\n'
    input_image_txt = input_image_txt[:-4]+'}\n'
    return input_image_txt

def str_weight_linear(weight, tensor_name):
    out_ch, in_ch  = weight.size(0), weight.size(1)
    str_v = '#define '+tensor_name+' {'
    for v in range(out_ch):
        for k in range(in_ch):
            str_v += str(int(weight[v][k].item())) + ', '
        str_v += '\\\n'
    str_v = str_v[:-4]+'}\n'
    return str_v

def clip8(conv, bits, signed=False):
    if signed:
        upper = (2**(bits-1)-1)
        lower = -(2**(bits-1))
    else:
        upper = (2**bits) - 1
        lower = 0
    conv[conv >= upper] = upper
    conv[conv <= lower] = lower
    #out = np.uint8(conv)
    out = conv
    return out

def matmul_mixed_tests_generator(layer, kernel):
    # print("Matmul Mixed Test Generator (type: " + str(kernel.type) +
    #                                     ", bn: " + str(layer.bn) +
    #                                     ", relu: " + str(layer.relu) +
    #                                     ", quant: " + str(kernel.quantization) +
    #                                     ", ISA: " + str(kernel.extentions) +
    #                                     ")")
    torch.manual_seed(5)
    random.seed(5)
    # input vectors
    if kernel.in_signed:
        upper_in_clip = 2**(kernel.in_data_t-1)
        lower_in_clip = -upper_in_clip
    else:
        upper_in_clip = 2**kernel.in_data_t
        lower_in_clip = 0

    x = torch.Tensor(1, layer.ch_in*layer.dim_in_y*layer.dim_in_x).random_(lower_in_clip, upper_in_clip)
    # weights matrix
    w = torch.Tensor(1, layer.ch_in*layer.dim_in_y*layer.dim_in_x*layer.ch_out).random_(-(2**(kernel.wt_data_t-1)),(2**(kernel.wt_data_t-1)))

    net = nn.Sequential(torch.matmul(x,w),
                        PULPNNBatchNorm(Cin = layer.ch_out, Kh = layer.ker_y, Kw =layer.ker_x, BitA = kernel.in_data_t, BitW = kernel.wt_data_t, BitO=kernel.out_data_t, SgnO=kernel.out_signed) if (layer.bn==True and layer.relu==True) else (
                        PULPNNReLu(BitO=kernel.out_data_t, SgnO=kernel.out_signed) if layer.relu == True else (
                        PULPNNShiftClip(BitO=kernel.out_data_t, SgnO=kernel.out_signed) if kernel.quantization=='shift_clip' else
                        ScaledThresholdsQuantization4d(num_bits=kernel.out_data_t))))

    bias_shift = 0
    out_mult = 0
    out_shift = 0

    str_out = '#define BIAS_SHIFT '+ str(bias_shift) +'\n'

    if layer.bias == True:
        net[0].bias.data.random_(-(2**(15)),(2**(15) -1))
        str_out += str_tensor(net[0].bias.data, 'BIAS')

    if layer.bn == True and layer.relu == True:
        str_out += str_tensor(net[1].k, 'KAPPA')
        str_out += str_tensor(net[1].l, 'LAMBDA')
        str_out += '#define OUT_SHIFT '+ str(int(net[1].d.item()))+'\n'
        str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
    else:
        # Setting relu parameters
        if layer.relu == True:
            net[1].out_mult = out_mult
            net[1].out_shift = out_shift
            str_out += '#define OUT_MULT '+ str(int(net[1].out_mult.item()))+'\n'
            str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift.item()))+'\n'
        else:

            if kernel.quantization == 'shift_clip':
                # Setting shift and clip quantization parameters
                net[1].out_shift = torch.Tensor([out_shift])
                str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
                str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift.item()))+'\n'
            else:
                # Setting quantization thresholds
                net[1].thresholds = torch.Tensor(layer.ch_out,2**kernel.out_data_t-1)
                net[1].signs = torch.Tensor(layer.ch_out).fill_(1)
                for r in range(net[1].thresholds.size(0)):
                    base = torch.Tensor(1).random_(0,layer.ker_x*layer.ker_y*layer.ch_in*(2**(kernel.in_data_t-1)-1 ))
                    for s in range(net[1].thresholds.size(1) ):
                        if net[1].signs[r]==1:
                            net[1].thresholds[r][s] = int(torch.clamp(- base*(2**(kernel.out_data_t-1)) + base*s, -32768, 32767).item())
                        else:
                            net[1].thresholds[r][s] = int(torch.clamp(base*(2**(kernel.out_data_t-1)) - base*s, -32768, 32767).item())
                str_out += str_thr(net[1].thresholds,'THR_INT' + str(kernel.out_data_t))
    # Running the network
    y = net(x)

    str_out += str_tensor(x, 'IN_INT'+ str(8))
    str_out += str_tensor(w, 'WEIGHT_INT' + str(kernel.wt_data_t))
    str_out += str_tensor(torch.Tensor(y), 'OUT_INT' + str(kernel.out_data_t))

    return str_out

# Generating all convolution kernels (default: standard convolution) followed by all quantization possibilities (default: bn+shift_clip)
def convolution_mixed_tests_generator(layer, kernel):
    # print("Convolution Mixed Test Generator (type: " + str(kernel.type) +
    #                                             ", in_data_t: " + str(kernel.in_data_t) +
    #                                             ", out_data_t: " + str(kernel.out_data_t) +
    #                                             ", wt_data_t: " + str(kernel.wt_data_t) +
    #                                             ", bn: " + str(layer.bn) +
    #                                             ", act_prec: " + str(kernel.act_prec) +
    #                                             ", relu: " + str(layer.relu) +
    #                                             ", quant: " + str(kernel.quantization) +
    #                                             ", ISA: " + str(kernel.extentions) +
    #                                             ")")
    torch.manual_seed(10)
    random.seed(4)
    # input vectors
    if kernel.in_signed:
        upper_in_clip = 2**(kernel.in_data_t-1)
        lower_in_clip = -upper_in_clip
    else:
        upper_in_clip = 2**kernel.in_data_t
        lower_in_clip = 0
    # Setting input activations
    x = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(lower_in_clip, upper_in_clip)
    #x = torch.clamp(torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).normal_(mean=(2**(kernel.in_data_t-1)),std=(2**(kernel.in_data_t-2))), min=0, max=(2**(kernel.in_data_t)-1))
    #x = torch.round(x)
    # Setting biases
    bias_shift = 0
    out_mult = 0
    out_shift = 0
    # Setting the network
    net = nn.Sequential(nn.Conv2d(in_channels=layer.ch_in, out_channels=layer.ch_out, kernel_size=layer.ker_x, stride=layer.stride_x, padding=layer.pad_y_top, groups=(1 if kernel.type != 'depthwise' else layer.ch_in), bias=layer.bias),
                        PULPNNBatchNorm(Cin = layer.ch_out, Kh = layer.ker_y, Kw =layer.ker_x, BitA = kernel.in_data_t, BitW = kernel.wt_data_t, BitO=kernel.out_data_t, SgnO=kernel.out_signed) if (layer.bn==True and layer.relu==True) else (
                        PULPNNReLu(BitO=kernel.out_data_t, SgnO=kernel.out_signed) if layer.relu == True else (
                        PULPNNShiftClip(BitI=kernel.in_data_t, BitW=kernel.wt_data_t, BitO=kernel.out_data_t, SgnO=kernel.out_signed) if kernel.quantization=='shift_clip' else
                        ScaledThresholdsQuantization4d(num_bits=kernel.out_data_t))))

    # Setting weights
    net[0].weight.data.random_(-(2**(kernel.wt_data_t-1)),(2**(kernel.wt_data_t-1))-1)
    #net[0].weight.data = torch.clamp(net[0].weight.data.normal_(mean=0, std=(2**(kernel.wt_data_t-2))), min=-(2**(kernel.wt_data_t-1)), max=((2**(kernel.wt_data_t-1))-1))
    #net[0].weight.data = torch.round(net[0].weight.data)

    str_out = str_weight(net[0].weight.data, 'WEIGHT_INT' + str(kernel.wt_data_t))

    str_out += '#define BIAS_SHIFT '+ str(bias_shift) +'\n'

    if layer.bias == True:
        net[0].bias.data.random_(-(2**(15)),(2**(15) -1))
        str_out += str_tensor(net[0].bias.data, 'BIAS')

    if layer.bn == True and layer.relu == True:
        str_out += str_tensor(net[1].k, 'KAPPA')
        str_out += str_tensor(net[1].l, 'LAMBDA')
        str_out += '#define OUT_SHIFT '+ str(int(net[1].d.item()))+'\n'
        str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
    else:
        # Setting relu parameters
        if layer.relu == True:
            net[1].out_mult = out_mult
            net[1].out_shift = out_shift
            str_out += '#define OUT_MULT '+ str(int(net[1].out_mult.item()))+'\n'
            str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift.item()))+'\n'
        else:

            if kernel.quantization == 'shift_clip':
                # Setting shift and clip quantization parameters
                #net[1].out_shift = out_shift
                str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
                str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift))+'\n'
            else:
                # Setting quantization thresholds
                net[1].thresholds = torch.Tensor(layer.ch_out,2**kernel.out_data_t-1)
                net[1].signs = torch.Tensor(layer.ch_out).fill_(1)
                for r in range(net[1].thresholds.size(0)):
                    base = torch.Tensor(1).random_(0,layer.ker_x*layer.ker_y*layer.ch_in*(2**(kernel.in_data_t-1)-1 ))
                    for s in range(net[1].thresholds.size(1) ):
                        if net[1].signs[r]==1:
                            net[1].thresholds[r][s] = int(torch.clamp(- base*(2**(kernel.out_data_t-1)) + base*s, -32768, 32767).item())
                        else:
                            net[1].thresholds[r][s] = int(torch.clamp(base*(2**(kernel.out_data_t-1)) - base*s, -32768, 32767).item())
                str_out += str_thr(net[1].thresholds,'THR_INT' + str(kernel.out_data_t))
    # Running the network
    y = net(x)

    str_out += str_tensor(x, 'IN_INT'+ str(kernel.in_data_t))
    str_out += str_tensor(torch.Tensor(y), 'OUT_INT' + str(kernel.out_data_t))

    return str_out

# Generating all linear kernels (default: linear with quantized output) followed by all output possibilities (default: bn+shift_clip)
def linear_mixed_tests_generator(layer, kernel):
    # print("Linear Mixed Test Generator (type: " + str(kernel.type) +
    #                                         ", in_data_t: " + str(kernel.in_data_t) +
    #                                         ", out_data_t: " + str(kernel.out_data_t) +
    #                                         ", wt_data_t: " + str(kernel.wt_data_t) +
    #                                         ", bn: " + str(layer.bn) +
    #                                         ", act_prec: " + str(kernel.act_prec) +
    #                                         ", relu: " + str(layer.relu) +
    #                                         ", quant: " + str(kernel.quantization) +
    #                                         ", ISA: " + str(kernel.extentions) +
    #                                         ")")
    torch.manual_seed(5)
    random.seed(5)
    if kernel.in_signed:
        upper_in_clip = 2**(kernel.in_data_t-1)
        lower_in_clip = -upper_in_clip
    else:
        upper_in_clip = 2**kernel.in_data_t
        lower_in_clip = 0
    # Setting input activations
    x = torch.Tensor(1,layer.ch_in*layer.dim_in_y*layer.dim_in_x).random_(lower_in_clip, upper_in_clip)
    # Setting the network
    if kernel.quantization != None:
        net = nn.Sequential(nn.Linear(layer.ch_in*layer.dim_in_y*layer.dim_in_x, layer.ch_out, bias=layer.bias),
                            (PULPNN1DBatchNorm(Cin = layer.ch_out, BitA = kernel.in_data_t, BitW = kernel.wt_data_t, BitO=kernel.out_data_t, SgnO=kernel.out_signed) if (layer.bn==True and layer.relu==True) else (
                            PULPNNReLu(BitO=kernel.out_data_t, SgnO=kernel.out_signed) if (layer.relu == True) else (
                            PULPNNShiftClip(BitO=kernel.out_data_t, SgnO=kernel.out_signed) if (kernel.quantization=='shift_clip') else
                            ScaledThresholdsQuantization4d(num_bits=kernel.out_data_t)))))
    else:
        net = nn.Sequential(nn.Linear(layer.ch_in*layer.dim_in_y*layer.dim_in_x, layer.ch_out, bias=layer.bias))

    # Setting weights
    net[0].weight.data.random_(-(2**(kernel.wt_data_t-1)),(2**(kernel.wt_data_t-1) -1))
    str_out = str_weight_linear(net[0].weight.data, 'WEIGHT_INT' + str(kernel.wt_data_t))
    # Setting biases
    bias_shift = 0
    out_mult = 0
    out_shift = 0

    str_out += '#define BIAS_SHIFT '+ str(bias_shift) +'\n'

    if layer.bias == True:
        net[0].bias.data.random_(-(2**(15)),(2**(15) -1))
        str_out += str_tensor(net[0].bias.data, 'BIAS')

    if kernel.quantization != None:
        if layer.bn == True and layer.relu == True:
            str_out += str_tensor_linear(net[1].k, 'KAPPA')
            str_out += str_tensor_linear(net[1].l, 'LAMBDA')
            str_out += '#define OUT_SHIFT '+ str(int(net[1].d.item()))+'\n'
            str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
        else:
            # Setting relu parameters
            if layer.relu == True:
                net[1].out_mult = torch.Tensor([out_mult])
                net[1].out_shift = torch.Tensor([out_shift])
                str_out += '#define OUT_MULT '+ str(int(net[1].out_mult.item()))+'\n'
                str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift.item()))+'\n'
            else:
                if kernel.quantization == 'shift_clip':
                    # Setting shift and clip quantization parameters
                    net[1].out_shift = torch.Tensor([out_shift])
                    str_out += '#define OUT_MULT '+ str(out_mult) +'\n'
                    str_out += '#define OUT_SHIFT '+ str(int(net[1].out_shift.item()))+'\n'
                else:
                    # Setting quantization thresholds
                    net[1].thresholds = torch.Tensor(layer.ch_out,2**kernel.out_data_t-1)
                    net[1].signs = torch.Tensor(layer.ch_out).fill_(1)
                    for r in range(net[1].thresholds.size(0)):
                        base = torch.Tensor(1).random_(0,layer.ker_x*layer.ker_y*layer.ch_in*(2**(kernel.in_data_t-1)-1 ))
                        for s in range(net[1].thresholds.size(1) ):
                            if net[1].signs[r]==1:
                                net[1].thresholds[r][s] = int(torch.clamp(- base*(2**(kernel.out_data_t-1)) + base*s, -32768, 32767).item())
                            else:
                                net[1].thresholds[r][s] = int(torch.clamp(base*(2**(kernel.out_data_t-1)) - base*s, -32768, 32767).item())
                    str_out += str_thr(net[1].thresholds,'THR_INT' + str(kernel.out_data_t))

    else:
        str_out += '#define OUT_MULT ' + str(out_shift) +'\n'
        str_out += '#define OUT_SHIFT '+ str(out_mult) +'\n'

    # Running the network
    y = net(x)

    str_out += str_tensor_linear(x, 'IN_INT'+ str(kernel.in_data_t))
    str_out += str_tensor_linear(torch.Tensor(y), 'OUT_INT' + str(kernel.out_data_t))

    return str_out

def pooling_mixed_tests_generator(layer, kernel):
    # print("Pooling Mixed Test Generator (type: " + str(kernel.type) +
    #                                     ", ISA: " + str(kernel.extentions) +
    #                                     ")")
    torch.manual_seed(5)
    random.seed(5)
    str_out = ""
    if kernel.in_signed:
        upper_in_clip = 2**(kernel.in_data_t-1)
        lower_in_clip = -upper_in_clip
    else:
        upper_in_clip = 2**kernel.in_data_t
        lower_in_clip = 0
    # Setting input activations
    x = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(lower_in_clip, upper_in_clip)
    # Setting the network
    if kernel.type == "maxpool":
        net = nn.MaxPool2d(layer.pool_kernel, layer.pool_stride)
    else:
        layers = [nn.AvgPool2d(layer.pool_kernel, layer.pool_stride)]
        layers.append(PULPNNBatchNorm(Cin = layer.ch_out, Kh = layer.pool_kernel, Kw =layer.pool_kernel, BitA = kernel.in_data_t, BitW = 0, BitO=kernel.out_data_t, SgnO=kernel.out_signed))
        # only a single multiply, add, shift
        # make sure k is divisible by total kernel size
        layers[1].k = (layers[1].k.squeeze()[0:1].clone()).floor()*layer.pool_kernel*layer.pool_kernel
        layers[1].l = layers[1].l.squeeze()[0:1].clone()
        net = nn.Sequential(*layers)
        if layer.bn:
            str_out += f"#define OUT_MULT ({int(net[1].k.item())})\n"
            str_out += f"#define OUT_ADD ({int(net[1].l.item())})\n"
            str_out += f"#define OUT_SHIFT ({int(net[1].d.item())})\n"
            # when BN is enabled, we fold the division by kernel size into the
            # multiplication, so the model layer must take this into account
    #        net[1].k *= (layer.pool_kernel**2)
        else:
            # when no BN is used, we use the BN layer just to floor the test
            # network's output
            net[1].k.fill_(1.)
            net[1].l.fill_(0.)
            net[1].d.fill_(0.)

    # Running the network
    y = net(x)

    str_out += str_tensor(x, 'IN_INT'+ str(kernel.in_data_t))
    str_out += str_tensor(torch.Tensor(y), 'OUT_INT' + str(kernel.out_data_t))

    return str_out

def add_mixed_tests_generator(layer, kernel):
    # print("Add Mixed Test Generator (type: " + str(kernel.type) +
    #                                 ", ISA: " + str(kernel.extentions) +
    #                                 ")")
    torch.manual_seed(5)
    random.seed(5)
    # Setting input activations
    x1 = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(0,(2**(kernel.in_data_t) - 1))
    x2 = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(0,(2**(kernel.out_data_t) - 1))

    # Setting scaling parameters
    m1 = 5
    m2 = 5
    out_shift = 3

    # Running the network
    y = clip8(((x1 * m1)+(x2 * m2)) >> out_shift, kernel.in_data_t if kernel.in_data_t > kernel.out_data_t else kernel.out_data_t)

    str_out = '#define OUT_MULT1 ' + str(m1) +'\n'
    str_out += '#define OUT_MULT2 ' + str(m2) +'\n'
    str_out += '#define OUT_SHIFT '+ str(out_shift) +'\n'

    str_out += str_tensor(x1, 'IN1_INT'+ str(kernel.in_data_t))
    str_out += str_tensor(x2, 'IN2_INT'+ str(kernel.out_data_t))
    str_out += str_tensor(torch.Tensor(y), 'OUT_INT' + str(kernel.in_data_t if kernel.in_data_t > kernel.out_data_t else kernel.out_data_t))

    return str_out


def quant_add_mixed_tests_generator(layer, kernel):
    # print("Add Mixed Test Generator (type: " + str(kernel.type) +
    #                                 ", ISA: " + str(kernel.extentions) +
    #                                 ")")

    
    torch.manual_seed(5)
    random.seed(5)
    # Setting input activations
    x1 = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(0,(2**(kernel.in_data_t) - 1))
    x2 = torch.Tensor(1,layer.ch_in,layer.dim_in_y,layer.dim_in_x).random_(0,(2**(kernel.out_data_t) - 1))

    # Setting scaling parameters
    m1 = 5
    m2 = 5
    out_shift = 3

    # Running the network
    y = clip8(((x1 * m1)+(x2 * m2)) >> out_shift, kernel.in_data_t if kernel.in_data_t > kernel.out_data_t else kernel.out_data_t)

    str_out = '#define OUT_MULT1 ' + str(m1) +'\n'
    str_out += '#define OUT_MULT2 ' + str(m2) +'\n'
    str_out += '#define OUT_SHIFT '+ str(out_shift) +'\n'

    str_out += str_tensor(x1, 'IN1_INT'+ str(kernel.in_data_t))
    str_out += str_tensor(x2, 'IN2_INT'+ str(kernel.out_data_t))
    str_out += str_tensor(torch.Tensor(y), 'OUT_INT' + str(kernel.in_data_t if kernel.in_data_t > kernel.out_data_t else kernel.out_data_t))

    return str_out
