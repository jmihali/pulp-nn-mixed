/*
 * ${config.filename}
 * Nazareno Bruschi <nazareno.bruschi@unibo.it>
 *
 * Copyright (C) 2019-2020 University of Bologna
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "pmsis.h"
#include "pulp_nn_utils.h"
#include "pulp_nn_kernels.h"


<%
act_prec = int(config.kernel.act_prec[0:2])
act_t = f"int{act_prec}_t"
def su(sgn):
    return 's' if sgn else 'u'
def u_(sgn):
    return '' if sgn else 'u'
def s_(sgn):
    return 's' if sgn else ''

pt_in = f"{u_(config.kernel.in_signed)}int8_t"
vt_in = f"v4{su(config.kernel.in_signed)}"
int_t_in = f"{u_(config.kernel.in_signed)}int32_t"
pt_out = f"{u_(config.kernel.out_signed)}int8_t"
mac_fn = f"SumDotp{s_(config.kernel.in_signed)}{32//config.max_precision}"
out_clip_fn = f"clip{s_(config.kernel.out_signed)}{config.kernel.out_data_t}"
bex = f"bitext{u_(config.kernel.in_signed)}"
%>

void __attribute__((noinline)) ${config.fn_name}(
                        ${pt_in} *pIn,
                        ${pt_in} *pIm2ColBuffer,
                        int8_t *pBias,
                        ${pt_out} *pOut,
                        int8_t *pWeight,
                        ${act_t} *pKappa,
                        ${act_t} *pLambda,
                        uint16_t out_mult,
                        uint16_t out_shift,
                        uint16_t dim_in_x,
                        uint16_t dim_in_y,
                        uint16_t ch_in,
                        uint16_t dim_out_x,
                        uint16_t dim_out_y,
                        uint16_t ch_out,
                        uint16_t dim_kernel_x,
                        uint16_t dim_kernel_y,
                        uint16_t padding_y_top,
                        uint16_t padding_y_bottom,
                        uint16_t padding_x_left,
                        uint16_t padding_x_right,
                        uint16_t stride_x,
                        uint16_t stride_y,
                        uint8_t flag_relu,
                        uint8_t flag_batch_norm)
{
  uint16_t ch_in_r = PACK_INT${config.kernel.in_data_t}_SIZE(ch_in);
  uint16_t ch_out_r = PACK_INT${config.kernel.out_data_t}_SIZE(ch_out);

  int core_id = pi_core_id();
%if config.kernel.matmul_fmt == '4x2':
  ${pt_in} * pIm2ColBase = pIm2ColBuffer + (2 * core_id * PACK_INT${config.max_precision}_SIZE(ch_in) * dim_kernel_x * dim_kernel_y);
%elif config.kernel.matmul_fmt == '4x4':
  ${pt_in} * pIm2ColBase = pIm2ColBuffer + (4 * core_id * PACK_INT${config.max_precision}_SIZE(ch_in) * dim_kernel_x * dim_kernel_y);
%endif
  int i_out_y, i_out_x, i_ker_y, i_ker_x;
  int Log2Core;

  uint8_t extra_chunk = ((dim_out_y & (NUM_CORES-1)) != 0);
  uint8_t extra_chunk_r;
  uint16_t dim_out_x_r;
  uint8_t section;
  int core_id_r;

  if(extra_chunk && dim_out_x > 1)
  {
    Log2Core = log2(NUM_CORES >> 1);
    core_id_r = (core_id >> 1);
    dim_out_x_r = (dim_out_x >> 1);
    section = (core_id & 0x1);
    extra_chunk_r = ((dim_out_y & ((NUM_CORES >> 1) - 1)) != 0);
  }
  else
  {
    Log2Core = log2(NUM_CORES);
    core_id_r = core_id;
    dim_out_x_r = dim_out_x;
    section = 0;
    extra_chunk_r = extra_chunk;
    extra_chunk = 0;
  }

  uint8_t flag_dim_out_x_odd = dim_out_x & 0x01;

  int chunk = (dim_out_y >> Log2Core) + extra_chunk_r;

  int start_pixel = min((chunk * core_id_r), dim_out_y);
  int stop_pixel = min(start_pixel + chunk, dim_out_y);

  ${pt_in} *pIm2Col = pIm2ColBase;
  ${pt_out} *pOutBuffer = pOut + (start_pixel * ch_out_r * dim_out_x) + (section * ch_out_r * dim_out_x_r);

  for (i_out_y = start_pixel; i_out_y < stop_pixel; i_out_y++)
  {
    for(i_out_x=(section * dim_out_x_r); i_out_x<(dim_out_x_r + (section * (dim_out_x_r + flag_dim_out_x_odd))); i_out_x++)
    {
      if(i_out_y < padding_y_top)
      {
        for(i_ker_y=((i_out_y * stride_y) - padding_y_top); i_ker_y<((i_out_y * stride_y) - padding_y_top + dim_kernel_y); i_ker_y++)
        {
          for(i_ker_x=((i_out_x * stride_x) - padding_x_left); i_ker_x<((i_out_x * stride_x) - padding_x_left + dim_kernel_x); i_ker_x++)
          {
            if((i_ker_y < 0) || (i_ker_y >= dim_in_y) || (i_ker_x < 0) || (i_ker_x >= dim_in_x))
            {
              ${config.zeromem_fn}(pIm2Col, ch_in);
            }
            else
            {
              ${config.im2col_fn}((${pt_in}*) (pIn + ((i_ker_y * dim_in_x + i_ker_x) * ch_in_r)), pIm2Col, ch_in);
            }
            pIm2Col+=PACK_INT${config.max_precision}_SIZE(ch_in);
          }
        }
      }
      else if(i_out_y < dim_out_y - padding_y_bottom)
      {
        if(i_out_x < padding_x_left)
        {
          for(i_ker_y=((i_out_y * stride_y) - padding_y_top); i_ker_y<((i_out_y * stride_y) - padding_y_top + dim_kernel_y); i_ker_y++)
          {
            for(i_ker_x=((i_out_x * stride_x) - padding_x_left); i_ker_x<((i_out_x * stride_x) - padding_x_left + dim_kernel_x); i_ker_x++)
            {
              if((i_ker_x < 0) || (i_ker_x >= dim_in_x))
              {
                ${config.zeromem_fn}(pIm2Col, ch_in);
              }
              else
              {
                ${config.im2col_fn}((${pt_in}*) (pIn + ((i_ker_y * dim_in_x + i_ker_x) * ch_in_r)), pIm2Col, ch_in);
              }
              pIm2Col+=PACK_INT${config.max_precision}_SIZE(ch_in);
            }
          }
        }
        else if(i_out_x < (dim_out_x - padding_x_right))
        {
          for(i_ker_y=((i_out_y * stride_y) - padding_y_top); i_ker_y<((i_out_y * stride_y) - padding_y_top + dim_kernel_y); i_ker_y++)
          {
            ${config.im2col_fn}((${pt_in}*) pIn + (i_ker_y * dim_in_x + i_out_x * stride_x - padding_x_left)*ch_in_r,pIm2Col,ch_in * dim_kernel_x);
            pIm2Col+=PACK_INT${config.max_precision}_SIZE(ch_in * dim_kernel_x);
          }
        }
        else
        {
          for(i_ker_y=((i_out_y * stride_y) - padding_y_top); i_ker_y<((i_out_y * stride_y) - padding_y_top + dim_kernel_y); i_ker_y++)
          {
            for(i_ker_x = i_out_x * stride_x - padding_x_left; i_ker_x < i_out_x * stride_x - padding_x_left + dim_kernel_x; i_ker_x++)
            {
              if((i_ker_x < 0) || (i_ker_x >= dim_in_x))
              {
                ${config.zeromem_fn}(pIm2Col, ch_in);
              }
              else
              {
                ${config.im2col_fn}((${pt_in} *)pIn + (i_ker_y*dim_in_x+i_ker_x)* ch_in_r, pIm2Col, ch_in);
              }
              pIm2Col+=PACK_INT${config.max_precision}_SIZE(ch_in);
            }
          }
        }
      }
      else
      {
        for(i_ker_y=((i_out_y * stride_y) - padding_y_top); i_ker_y<((i_out_y * stride_y) - padding_y_top + dim_kernel_y); i_ker_y++)
        {
          for(i_ker_x = i_out_x * stride_x - padding_x_left; i_ker_x < i_out_x * stride_x - padding_x_left + dim_kernel_x; i_ker_x++)
          {
            if(i_ker_y < 0 || (i_ker_y >= dim_in_y) || i_ker_x < 0 || i_ker_x >= dim_in_x)
            {
              ${config.zeromem_fn}(pIm2Col, ch_in);
            }
            else
            {
              ${config.im2col_fn}((${pt_in} *) pIn + (i_ker_y * dim_in_x + i_ker_x) * ch_in_r, pIm2Col, ch_in);
            }
            pIm2Col+=PACK_INT${config.max_precision}_SIZE(ch_in);
          }
        }
      }
%if config.kernel.matmul_fmt == '4x2':
      if(pIm2Col == (pIm2ColBase + ((PACK_INT${config.max_precision}_SIZE(ch_in) * dim_kernel_x * dim_kernel_y) << 1)))
%elif config.kernel.matmul_fmt == '4x4':
      if(pIm2Col == (pIm2ColBase + ((PACK_INT${config.max_precision}_SIZE(ch_in) * dim_kernel_x * dim_kernel_y) << 2)))
%endif
      {
        pOutBuffer = ${config.mat_mul_fn}(
          pIm2ColBase,
          pBias,
          pOutBuffer,
          pOutBuffer + ch_out_r,
%if config.kernel.matmul_fmt == '4x4':
          pOutBuffer + (ch_out_r << 1),
          pOutBuffer + (ch_out_r << 1) + ch_out_r,
%endif
          pWeight,
          pKappa,
          pLambda,
          out_mult,
          out_shift,
          (ch_in * dim_kernel_x * dim_kernel_y),
          ch_out,
          flag_relu,
          flag_batch_norm
          );

        pIm2Col = pIm2ColBase;
      }
    }

    if(pIm2Col != pIm2ColBase)
    {
%if config.kernel.out_data_t == 2:
      int8_t mask2 = 0x0c;
      int8_t n_mask2 = ~ mask2;
      int8_t mask4 = 0x30;
      int8_t n_mask4 = ~ mask4;
      int8_t mask6 = 0xc0;
      int8_t n_mask6 = ~ mask6;
      int8_t off2 = 2;
      int8_t off4 = 4;
      int8_t off6 = 6;
%elif config.kernel.out_data_t == 4:
      int8_t mask = 0xf0;
      int8_t n_mask = ~ mask;
      int8_t off = 0x04;
%endif
      const int8_t *pA = pWeight;
      int i;
      ${act_t} * k1 = pKappa;
      ${act_t} * lambda1 = pLambda;

%if config.kernel.wt_data_t < config.kernel.in_data_t:
      v4s inA[${int(config.max_precision/config.kernel.wt_data_t)}];
%endif
      ${pt_out} out[${8//config.kernel.out_data_t}];
      uint16_t num_col_im2col = ch_in * dim_kernel_x * dim_kernel_y;
      uint16_t num_col_im2col_w = PACK_INT${config.kernel.wt_data_t}_SIZE(ch_in) * dim_kernel_x * dim_kernel_y;

      for(i = 0; i < ch_out; i++)
      {
        int sum = 0;
        if (pBias != NULL)
        {
          sum = ((int) (*pBias++));
        }

        ${pt_in} *pB = pIm2ColBase;

        int32_t *ptrA  = (int32_t *)pA;
        ${int_t_in} *ptrB = (${int_t_in} *)pB;
<%! import math %>
        for(int j=0; j < (num_col_im2col >> ${int(math.log2((int(32/config.max_precision))*(int(config.max_precision/config.kernel.wt_data_t))))}); j++)
        {
%if config.max_precision == 2:
          sum = ${mac_fn}(*(${int_t_in} *)ptrB, *(int32_t *)ptrA, sum);
          ptrA++;
          ptrB++;
%elif config.max_precision == 4:
%if config.kernel.wt_data_t < config.kernel.in_data_t:
          pA = ${config.unpack_wt_fn}(pA,inA);

          ptrA = (int32_t *)inA;

          sum = ${mac_fn}(*(${int_t_in} *)ptrB, *(int32_t *)ptrA, sum);

          ptrA++;
          ptrB++;

          sum = ${mac_fn}(*(${int_t_in} *)ptrB, *(int32_t *)ptrA, sum);

          ptrA++;
          ptrB++;
%else:
   sum = ${mac_fn}(*(${int_t_in} *)ptrB, *(int32_t *)ptrA, sum);
          ptrA++;
          ptrB++;
%endif
%elif config.max_precision == 8:
%if config.kernel.wt_data_t < config.kernel.in_data_t:
%if config.kernel.wt_data_t == 2:
          pA = ${config.unpack_wt_fn}(pA,inA);

          ptrA = (int32_t *)inA;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;
%elif config.kernel.wt_data_t == 4:
          pA = ${config.unpack_wt_fn}(pA,inA);

          ptrA = (int32_t *)inA;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;

          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);

          ptrA++;
          ptrB++;
%endif
%else:
          sum = ${mac_fn}(*(${vt_in} *)ptrB, *(v4s *)ptrA, sum);
          ptrA++;
          ptrB++;
%endif
%endif
        }

        int col_cnt_im2col = num_col_im2col & ${hex((((int(32/config.max_precision))*(int(config.max_precision/config.kernel.wt_data_t))))-1)};

        if(col_cnt_im2col)
        {
%if config.kernel.wt_data_t >= config.kernel.in_data_t:
          uint16_t loop_cnt_im2col_w = (num_col_im2col >> ${int(math.log2(((int(32/config.max_precision))*(int(config.max_precision/config.kernel.wt_data_t)))))}) << 2;
          pA+=loop_cnt_im2col_w;
%endif

%if config.kernel.wt_data_t < config.kernel.in_data_t:
          uint16_t loop_cnt_im2col_a = (num_col_im2col >> ${int(math.log2(((int(32/config.max_precision))*(int(config.max_precision/config.kernel.wt_data_t)))))}) << ${int(2+int(math.log2(int(config.kernel.in_data_t/config.kernel.wt_data_t))))};
%else:
          uint16_t loop_cnt_im2col_a = (num_col_im2col >> ${int(math.log2(((int(32/config.max_precision))*(int(config.max_precision/config.kernel.wt_data_t)))))}) << 2;
%endif
          pB+=loop_cnt_im2col_a;

          do
          {
%if config.max_precision == 2:
            int8_t inA1 = (int8_t) bitext((int) *pA, 2, 0);
            ${pt_in} inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 2, 0);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 2);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 2, 2);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 4);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 2, 4);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 6);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 2, 6);
            sum += inA1 * inB1;

            pA++;
            pB++;
            col_cnt_im2col-=4;
%elif config.max_precision == 4:
%if config.kernel.wt_data_t < config.kernel.in_data_t:
            int8_t inA1 = (int8_t) bitext((int) *pA, 2, 0);
            ${pt_in} inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 0);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 2);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 4);
            sum += inA1 * inB1;
            pB++;
            inA1 = (int8_t) bitext((int) *pA, 2, 4);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 0);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 6);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 4);
            sum += inA1 * inB1;

            pA++;
            pB++;
            col_cnt_im2col-=4;
%else:
            int8_t inA1 = (int8_t) bitext((int) *pA, 4, 0);
            ${pt_in} inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 0);
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 4, 4);
            inB1 = (${pt_in}) ${bex}((${int_t_in}) *pB, 4, 4);
            sum += inA1 * inB1;

            pA++;
            pB++;
            col_cnt_im2col-=2;
%endif
%elif config.max_precision == 8:
%if config.kernel.wt_data_t < config.kernel.in_data_t:
%if config.kernel.wt_data_t == 2:
            int8_t inA1 = (int8_t) bitext((int) *pA, 2, 0);
            ${pt_in} inB1 = *pB++;
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 2);
            inB1 = *pB++;
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 4);
            inB1 = *pB++;
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 2, 6);
            inB1 = *pB++;
            sum += inA1 * inB1;

            pA++;
            col_cnt_im2col-=4;
%elif config.kernel.wt_data_t == 4:
            int8_t inA1 = (int8_t) bitext((int) *pA, 4, 0);
            ${pt_in} inB1 = *pB++;
            sum += inA1 * inB1;
            inA1 = (int8_t) bitext((int) *pA, 4, 4);
            inB1 = *pB++;
            sum += inA1 * inB1;

            pA++;
            col_cnt_im2col-=2;
%endif
%else:
            int8_t inA1 = *pA++;
            ${pt_in} inB1 = *pB++;
            asm volatile("": : :"memory");
            sum += inA1 * inB1;

            col_cnt_im2col--;
%endif
%endif
          } while(col_cnt_im2col);
%if config.kernel.wt_data_t >= config.kernel.in_data_t:
          pA-=num_col_im2col_w;
%endif
        }
%if config.kernel.out_data_t == 8 or config.kernel.quantization == 'shift_clip':
        if (flag_batch_norm && flag_relu)
        {
%if config.kernel.out_data_t == 8:
          *pOutBuffer = ${config.bn_fn}(sum, *k1, *lambda1, out_shift);
          k1++;
          lambda1++;
          pOutBuffer++;
%elif config.kernel.out_data_t == 4:
          uint8_t i_o = i & 0x01;
          out[i_o] = ${config.bn_fn}(sum, *k1, *lambda1, out_shift);
          k1++;
          lambda1++;
          if(i_o == 0x01)
          {
            *pOutBuffer = bitins(out[0], n_mask, out[1], mask, off);
            pOutBuffer++;
          }
%elif config.kernel.out_data_t == 2:
          uint8_t i_o = i & 0x03;
          out[i_o] = ${config.bn_fn}(sum, *k1, *lambda1, out_shift);
          k1++;
          lambda1++;
          if(i_o == 0x03)
          {
            out[0] = bitins(out[0], n_mask2, out[1], mask2, off2);
            out[0] = bitins(out[0], n_mask4, out[2], mask4, off4);
            *pOutBuffer = bitins(out[0], n_mask6, out[3], mask6, off6);
            pOutBuffer++;
          }
%endif
        }
        else
        {
          if(flag_relu == 1)
          {
%if config.kernel.out_data_t == 8:
            *pOutBuffer = ${config.relu_fn}(sum, out_mult, out_shift);
            pOutBuffer++;
%elif config.kernel.out_data_t == 4:
            uint8_t i_o = i & 0x01;
            out[i_o] = ${config.relu_fn}(sum, out_mult, out_shift);
            if(i_o == 0x01)
            {
              *pOutBuffer = bitins(out[0], n_mask, out[1], mask, off);
              pOutBuffer++;
            }
%elif config.kernel.out_data_t == 2:
            uint8_t i_o = i & 0x03;
            out[i_o] = ${config.relu_fn}(sum, out_mult, out_shift);
            if(i_o == 0x03)
            {
              out[0] = bitins(out[0], n_mask2, out[1], mask2, off2);
              out[0] = bitins(out[0], n_mask4, out[2], mask4, off4);
              *pOutBuffer = bitins(out[0], n_mask6, out[3], mask6, off6);
              pOutBuffer++;
            }
%endif
          }
          else
          {
%if config.kernel.out_data_t == 8:
            *pOutBuffer = (${pt_out}) ${out_clip_fn}(sum >> out_shift);
            pOutBuffer++;
%elif config.kernel.out_data_t == 4:
            uint8_t i_o = i & 0x01;
            out[i_o] = (${pt_out}) ${out_clip_fn}(sum >> out_shift);
            if(i_o == 0x01)
            {
              *pOutBuffer = bitins(out[0], n_mask, out[1], mask, off);
              pOutBuffer++;
            }
%elif config.kernel.out_data_t == 2:
            uint8_t i_o = i & 0x03;
            out[i_o] = (${pt_out}) ${out_clip_fn}(sum >> out_shift);
            if(i_o == 0x03)
            {
              out[0] = bitins(out[0], n_mask2, out[1], mask2, off2);
              out[0] = bitins(out[0], n_mask4, out[2], mask4, off4);
              *pOutBuffer = bitins(out[0], n_mask6, out[3], mask6, off6);
              pOutBuffer++;
            }
%endif
          }
        }
%elif config.kernel.out_data_t == 4:
        uint8_t i_o = i & 0x01;
        out[i_o] = pulp_nn_i4_quant(sum, pThr);
        pThr++;
        if(i_o == 0x01)
        {
          *pOutBuffer = bitins(out[0], n_mask, out[1], mask, off);
          pOutBuffer++;
        }
%elif config.kernel.out_data_t == 2:
        uint8_t i_o = i & 0x03;
        out[i_o] = pulp_nn_i2_quant(sum, pThr);
        pThr++;
        if(i_o == 0x03)
        {
          out[0] = bitins(out[0], n_mask2, out[1], mask2, off2);
          out[0] = bitins(out[0], n_mask4, out[2], mask4, off4);
          *pOutBuffer = bitins(out[0], n_mask6, out[3], mask6, off6);
          pOutBuffer++;
        }
%endif
%if config.kernel.wt_data_t >= config.kernel.in_data_t:
        pA+=num_col_im2col_w;
%endif
      }
    }
    pOutBuffer+=(extra_chunk * ((dim_out_x_r + ((1 - section) * flag_dim_out_x_odd)) * ch_out_r));
    pIm2Col = pIm2ColBase;
  }
  pi_cl_team_barrier(0);
}
