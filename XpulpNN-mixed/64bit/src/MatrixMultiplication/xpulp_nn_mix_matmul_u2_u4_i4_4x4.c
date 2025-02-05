/*
 * xpulp_nn_mix_matmul_u2_u4_i4_4x4.c
 * Nazareno   Bruschi  <nazareno.bruschi@unibo.it>
 * Alessandro Nadalini <alessandro.nadalini3@unibo.it>
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


uint8_t * __attribute__((noinline)) xpulp_nn_mix_matmul_u2_u4_i4_4x4(
                        uint8_t *pIn,
                        int8_t *pBias,
                        uint8_t *pOut,
                        uint8_t *pOut2,
                        uint8_t *pOut3,
                        uint8_t *pOut4,
                        int8_t *pWeight,
                        int64_t *pKappa,
                        int64_t *pLambda,
                        uint16_t out_mult,
                        uint16_t out_shift,
                        uint16_t num_col_im2col,
                        uint16_t ch_out,
                        uint8_t flag_relu,
                        uint8_t flag_batch_norm)
{
  int8_t mask = 0xf0;
  int8_t n_mask = ~ mask;
  int8_t off = 0x04;

  uint16_t ch_out_r = PACK_INT4_SIZE(ch_out);

  uint16_t num_col_im2col_w = PACK_INT4_SIZE(num_col_im2col);
  uint16_t num_col_im2col_a = PACK_INT4_SIZE(num_col_im2col);

  int32_t a_rollback = 4 - (num_col_im2col_a + (num_col_im2col_a << 1));
  int32_t w_rollback = 4 - (num_col_im2col_w + (num_col_im2col_w << 1));

  LEGACY_MODE("0");
  A_STRIDE(num_col_im2col_a);
  W_STRIDE(num_col_im2col_w);
  A_ROLLBACK(a_rollback);
  W_ROLLBACK(w_rollback);
  A_SKIP("3");
  W_SKIP("3");
  MIXED_SKIP("16");

  int8_t *pA = pWeight;

  uint16_t chan_left = ch_out & 0x3;

  for(int i=0; i < (ch_out >> 2); i++)
  {
    uint8_t *pB =  pIn;

    uint32_t *ptrB  = (uint32_t *) pB;

    int32_t *ptrA  = (int32_t *) pA ;

    A_ADDRESS(ptrB);
    W_ADDRESS(ptrA);

    ptrA = MacLoadInit(1, 0, 0, 0, ptrA);
    ptrA = MacLoadInit(1, 0, 1, 0, ptrA);
    ptrA = MacLoadInit(1, 0, 2, 0, ptrA);
    ptrA = MacLoadInit(1, 0, 3, 0, ptrA);

    ptrB = MacLoadInit(0, 1, 0, 0, ptrB);

    int sum  = 0;
    int sum2 = 0;
    int sum3 = 0;
    int sum4 = 0;
    int sum5 = 0;
    int sum6 = 0;
    int sum7 = 0;
    int sum8 = 0;

    int sum9  = 0;
    int sum10 = 0;
    int sum11 = 0;
    int sum12 = 0;
    int sum13 = 0;
    int sum14 = 0;
    int sum15 = 0;
    int sum16 = 0;

    if (pBias != NULL)
    {
      sum = ((int) (*pBias++));
      sum2 = ((int) (*pBias++));
      sum3 = ((int) (*pBias++));
      sum4 = ((int) (*pBias++));

      sum5 = sum;
      sum6 = sum2;
      sum7 = sum3;
      sum8 = sum4;
    }

    for(int j=0; j<(num_col_im2col >> 3); j++)
    {
      ptrB = MacLoadInit(0, 1, 0, 1, ptrB);

      sum  = MacLoad8(0, 0, 0, 0, ptrA, sum);
      sum2 = MacLoad8(0, 0, 1, 0, ptrA, sum2);
      sum3 = MacLoad8(0, 0, 2, 0, ptrA, sum3);
      sum4 = MacLoad8(0, 1, 3, 0, ptrB, sum4);
      ptrB = MacLoadUpdate(ptrB);

      sum5 = MacLoad8(0, 0, 0, 1, ptrA, sum5);
      sum6 = MacLoad8(0, 0, 1, 1, ptrA, sum6);
      sum7 = MacLoad8(0, 0, 2, 1, ptrA, sum7);
      sum8 = MacLoad8(0, 1, 3, 1, ptrB, sum8);
      ptrB = MacLoadUpdate(ptrB);

      sum9  = MacLoad8(0, 0, 0, 0, ptrA, sum9);
      sum10 = MacLoad8(0, 0, 1, 0, ptrA, sum10);
      sum11 = MacLoad8(0, 0, 2, 0, ptrA, sum11);
      sum12 = MacLoad8(0, 1, 3, 0, ptrB, sum12);
      ptrB  = MacLoadUpdate(ptrB);

      sum13 = MacLoad8(1, 0, 0, 1, ptrA, sum13);
      ptrA  = MacLoadUpdate(ptrA);

      sum14 = MacLoad8(1, 0, 1, 1, ptrA, sum14);
      ptrA  = MacLoadUpdate(ptrA);

      sum15 = MacLoad8(1, 0, 2, 1, ptrA, sum15);
      ptrA  = MacLoadUpdate(ptrA);

      sum16 = MacLoad8(1, 0, 3, 1, ptrA, sum16);
      ptrA  = MacLoadUpdate(ptrA);

    }

    
    int col_cnt_im2col = num_col_im2col & 0x7;

    if(col_cnt_im2col)
    {
      uint16_t loop_cnt_im2col_w = (num_col_im2col >> 3) << 2;
      pA+=loop_cnt_im2col_w;

      uint16_t loop_cnt_im2col_a = (num_col_im2col >> 3) << 2;
      
      int8_t *pA2 = (pA  + num_col_im2col_w);
      int8_t *pA3 = (pA2 + num_col_im2col_w);
      int8_t *pA4 = (pA3 + num_col_im2col_w);

      pB+=loop_cnt_im2col_a;
      
      uint8_t *pB2 = (pB + loop_cnt_im2col_a);

      do
      {
        int8_t inA = (int8_t) bitext((int) *pA, 4, 0);
        int8_t inA2 = (int8_t) bitext((int) *pA2, 4, 0);
        int8_t inA3 = (int8_t) bitext((int) *pA3, 4, 0);
        int8_t inA4 = (int8_t) bitext((int) *pA4, 4, 0);

        uint8_t inB = (uint8_t)bitextu((unsigned int) *pB, 4, 0);
        uint8_t inB2 = (uint8_t)bitextu((unsigned int) *pB2, 4, 0);

        sum += inA * inB;
        sum2 += inA2 * inB;
        sum3 += inA3 * inB;
        sum4 += inA4 * inB;

        sum5 += inA * inB2;
        sum6 += inA2 * inB2;
        sum7 += inA3 * inB2;
        sum8 += inA4 * inB2;

        inA = (int8_t) bitext((int) *pA, 4, 4);
        inA2 = (int8_t) bitext((int) *pA2, 4, 4);
        inA3 = (int8_t) bitext((int) *pA3, 4, 4);
        inA4 = (int8_t) bitext((int) *pA4, 4, 4);

        inB = (uint8_t)bitextu((unsigned int) *pB, 4, 4);
        inB2 = (uint8_t)bitextu((unsigned int) *pB2, 4, 4);

        sum += inA * inB;
        sum2 += inA2 * inB;
        sum3 += inA3 * inB;
        sum4 += inA4 * inB;

        sum5 += inA * inB2;
        sum6 += inA2 * inB2;
        sum7 += inA3 * inB2;
        sum8 += inA4 * inB2;

        pA++;
        pA2++;
        pA3++;
        pA4++;

        pB++;
        pB2++;

        col_cnt_im2col-=2;
      } while(col_cnt_im2col);
      pA-=num_col_im2col_w;
    }
    if (flag_batch_norm && flag_relu)
    {
      sum   = pulp_nn_bn_quant_u4(sum, *pKappa, *pLambda, out_shift);
      sum5  = pulp_nn_bn_quant_u4(sum5, *pKappa, *pLambda, out_shift);
      sum9  = pulp_nn_bn_quant_u4(sum9, *pKappa, *pLambda, out_shift);
      sum13 = pulp_nn_bn_quant_u4(sum13, *pKappa, *pLambda, out_shift);
      pKappa++;
      pLambda++;
      sum2  = pulp_nn_bn_quant_u4(sum2, *pKappa, *pLambda, out_shift);
      sum6  = pulp_nn_bn_quant_u4(sum6, *pKappa, *pLambda, out_shift);
      sum10 = pulp_nn_bn_quant_u4(sum10, *pKappa, *pLambda, out_shift);
      sum14 = pulp_nn_bn_quant_u4(sum14, *pKappa, *pLambda, out_shift);
      *pOut = bitins(sum, n_mask, sum2, mask, off);
      *pOut2 = bitins(sum5, n_mask, sum6, mask, off);
      *pOut3 = bitins(sum9, n_mask, sum10, mask, off);
      *pOut4 = bitins(sum13, n_mask, sum14, mask, off);
      pKappa++;
      pLambda++;
      pOut++;
      pOut2++;
      pOut3++;
      pOut4++;
      sum3 = pulp_nn_bn_quant_u4(sum3, *pKappa, *pLambda, out_shift);
      sum7 = pulp_nn_bn_quant_u4(sum7, *pKappa, *pLambda, out_shift);
      sum11 = pulp_nn_bn_quant_u4(sum11, *pKappa, *pLambda, out_shift);
      sum15 = pulp_nn_bn_quant_u4(sum15, *pKappa, *pLambda, out_shift);
      pKappa++;
      pLambda++;
      sum4 = pulp_nn_bn_quant_u4(sum4, *pKappa, *pLambda, out_shift);
      sum8 = pulp_nn_bn_quant_u4(sum8, *pKappa, *pLambda, out_shift);
      sum12 = pulp_nn_bn_quant_u4(sum12, *pKappa, *pLambda, out_shift);
      sum16 = pulp_nn_bn_quant_u4(sum16, *pKappa, *pLambda, out_shift);
      pKappa++;
      pLambda++;
      *pOut = bitins(sum3, n_mask, sum4, mask, off);
      *pOut2 = bitins(sum7, n_mask, sum8, mask, off);
      *pOut3 = bitins(sum11, n_mask, sum12, mask, off);
      *pOut4 = bitins(sum15, n_mask, sum16, mask, off);
      pOut++;
      pOut2++;
      pOut3++;
      pOut4++;
    }
    else
    {
      if (flag_relu == 1)
      {
        sum = pulp_nn_quant_u4(sum, out_mult, out_shift);
        sum2 = pulp_nn_quant_u4(sum2, out_mult, out_shift);
        *pOut = bitins(sum, n_mask, sum2, mask, off);
        pOut++;
        sum3 = pulp_nn_quant_u4(sum3, out_mult, out_shift);
        sum4 = pulp_nn_quant_u4(sum4, out_mult, out_shift);
        *pOut = bitins(sum3, n_mask, sum4, mask, off);
        pOut++;

        sum5 = pulp_nn_quant_u4(sum5, out_mult, out_shift);
        sum6 = pulp_nn_quant_u4(sum6, out_mult, out_shift);
        *pOut2 = bitins(sum5, n_mask, sum6, mask, off);
        pOut2++;
        sum7 = pulp_nn_quant_u4(sum7, out_mult, out_shift);
        sum8 = pulp_nn_quant_u4(sum8, out_mult, out_shift);
        *pOut2 = bitins(sum7, n_mask, sum8, mask, off);
        pOut2++;

        sum9  = pulp_nn_quant_u4(sum9, out_mult, out_shift);
        sum10 = pulp_nn_quant_u4(sum10, out_mult, out_shift);
        *pOut3 = bitins(sum9, n_mask, sum10, mask, off);
        pOut3++;
        sum11 = pulp_nn_quant_u4(sum11, out_mult, out_shift);
        sum12 = pulp_nn_quant_u4(sum12, out_mult, out_shift);
        *pOut3 = bitins(sum11, n_mask, sum12, mask, off);
        pOut3++;

        sum13 = pulp_nn_quant_u4(sum13, out_mult, out_shift);
        sum14 = pulp_nn_quant_u4(sum14, out_mult, out_shift);
        *pOut4 = bitins(sum13, n_mask, sum14, mask, off);
        sum15 = pulp_nn_quant_u4(sum15, out_mult, out_shift);
        sum16 = pulp_nn_quant_u4(sum16, out_mult, out_shift);
        *pOut4 = bitins(sum15, n_mask, sum16, mask, off);
      }
      else
      {
        sum = (uint8_t) clip4(sum >> out_shift);
        sum2 = (uint8_t) clip4(sum2 >> out_shift);
        *pOut = bitins(sum, n_mask, sum2, mask, off);
        pOut++;
        sum3 = (uint8_t) clip4(sum3 >> out_shift);
        sum4 = (uint8_t) clip4(sum4 >> out_shift);
        *pOut = bitins(sum3, n_mask, sum4, mask, off);
        pOut++;

        sum5 = (uint8_t) clip4(sum5 >> out_shift);
        sum6 = (uint8_t) clip4(sum6 >> out_shift);
        *pOut2 = bitins(sum5, n_mask, sum6, mask, off);
        pOut2++;
        sum7 = (uint8_t) clip4(sum7 >> out_shift);
        sum8 = (uint8_t) clip4(sum8 >> out_shift);
        *pOut2 = bitins(sum7, n_mask, sum8, mask, off);
        pOut2++;

        sum9  = (uint8_t) clip4(sum9 >> out_shift);
        sum10 = (uint8_t) clip4(sum10 >> out_shift);
        *pOut3 = bitins(sum9, n_mask, sum10, mask, off);
        pOut3++;
        sum11 = (uint8_t) clip4(sum11 >> out_shift);
        sum12 = (uint8_t) clip4(sum12 >> out_shift);
        pOut3++;

        sum13 = (uint8_t) clip4(sum13 >> out_shift);
        sum14 = (uint8_t) clip4(sum14 >> out_shift);
        *pOut4 = bitins(sum13, n_mask, sum14, mask, off);
        pOut4++;
        sum15 = (uint8_t) clip4(sum15 >> out_shift);
        sum16 = (uint8_t) clip4(sum16 >> out_shift);
        *pOut4 = bitins(sum15, n_mask, sum16, mask, off);
        pOut4++;
      }
    }
    pA+=(4 * num_col_im2col_w);
  }
  int i = 0;

  w_rollback = 4;
  W_ROLLBACK(w_rollback);
  W_SKIP("0");

  while(chan_left)
  {
    uint8_t *pB = pIn;

    int8_t *pA = pWeight + (num_col_im2col_w * (ch_out - chan_left));

    uint32_t *ptrB  = (uint32_t *) pB;

    int32_t *ptrA  = (int32_t *) pA;

    A_ADDRESS(ptrB);
    W_ADDRESS(ptrA);

    ptrA  = MacLoadInit(1, 0, 0, 0, ptrA);

    ptrB  = MacLoadInit(0, 1, 0, 0, ptrB);

    int sum = 0;
    if (pBias != NULL)
    {
      sum = ((int) (*pBias++));    
    }
    int sum2 = sum;

    uint8_t out[2];
    uint8_t out2[2];
    for(int j=0; j < (num_col_im2col >> 3); j++)
    {
      ptrB = MacLoadInit(0, 1, 0, 1, ptrB);

      sum  = MacLoad8(0, 1, 0, 0, ptrB, sum);
      ptrB = MacLoadUpdate(ptrB);

      sum2 = MacLoad8(1, 0, 0, 1, ptrA, sum2);
      ptrA = MacLoadUpdate(ptrA);
    }
    int col_cnt_im2col = num_col_im2col & 0x7;

    if(col_cnt_im2col)
    {
      uint16_t loop_cnt_im2col_w = (num_col_im2col >> 3) << 2;
      pA+=loop_cnt_im2col_w;

      uint16_t loop_cnt_im2col_a = (num_col_im2col >> 3) << 2;
      pB+=loop_cnt_im2col_a;
      
      uint8_t *pB2 = (pB +loop_cnt_im2col_a);

      int8_t *pA2 = (pA  + num_col_im2col_w);
      int8_t *pA3 = (pA2 + num_col_im2col_w);
      int8_t *pA4 = (pA3 + num_col_im2col_w);

      do
      {
        int8_t inA = (int8_t) bitext((int) *pA, 4, 0);

        uint8_t inB = (uint8_t)bitextu((unsigned int) *pB, 4, 0);
        uint8_t inB2 = (uint8_t)bitextu((unsigned int) *pB2, 4, 0);

        sum += inA * inB;

        sum2 += inA * inB2;

        inA = (int8_t) bitext((int) *pA, 4, 4);

        inB = (uint8_t)bitextu((unsigned int) *pB, 4, 0);
        inB2 = (uint8_t)bitextu((unsigned int) *pB2, 4, 0);

        sum += inA * inB;

        sum2 += inA * inB2;

        pA++;

        pB++;
        pB2++;

        col_cnt_im2col-=2;
      } while(col_cnt_im2col);
      pA-=num_col_im2col_w;
    }
    if (flag_batch_norm && flag_relu)
    {
      uint8_t i_o = i & 0x01;
      out[i_o] = pulp_nn_bn_quant_u4(sum, *pKappa, *pLambda, out_shift);
      out2[i_o] = pulp_nn_bn_quant_u4(sum2, *pKappa, *pLambda, out_shift);
      pKappa++;
      pLambda++;
      if(i_o == 0x01)
      {
        *pOut = bitins(out[0], n_mask, out[1], mask, off);
        *pOut2 = bitins(out2[0], n_mask, out2[1], mask, off);
        pOut++;
        pOut2++;
      }
    }
    else
    {
      if (flag_relu == 1)
      {
        uint8_t i_o = i & 0x01;
        out[i_o] = pulp_nn_quant_u4(sum, out_mult, out_shift);
        out2[i_o] = pulp_nn_quant_u4(sum2, out_mult, out_shift);
        if(i_o == 0x01)
        {
          *pOut = bitins(out[0], n_mask, out[1], mask, off);
          *pOut2 = bitins(out2[0], n_mask, out2[1], mask, off);
          pOut++;
          pOut2++;
        }
      }
      else
      {
        uint8_t i_o = i & 0x01;
        out[i_o] = (uint8_t) clip4(sum >> out_shift);
        out2[i_o] = (uint8_t) clip4(sum2 >> out_shift);
        if(i_o == 0x01)
        {
          *pOut = bitins(out[0], n_mask, out[1], mask, off);
          *pOut2 = bitins(out2[0], n_mask, out2[1], mask, off);
          pOut++;
          pOut2++;
        }
      }
    }
    i++;
    pA+=num_col_im2col_w;
    chan_left--;
  }
  pOut+=ch_out_r;
  return pOut;
}
