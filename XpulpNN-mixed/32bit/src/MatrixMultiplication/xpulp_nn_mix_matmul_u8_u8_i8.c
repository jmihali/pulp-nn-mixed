/*
 * xpulp_nn_mix_matmul_u8_u8_i8.c
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


uint8_t * __attribute__((noinline)) xpulp_nn_mix_matmul_u8_u8_i8(
                        uint8_t *pIn,
                        int8_t *pBias,
                        uint8_t *pOut,
                        uint8_t *pOut2,
                        int8_t *pWeight,
                        int32_t *pKappa,
                        int32_t *pLambda,
                        uint16_t out_mult,
                        uint16_t out_shift,
                        uint16_t num_col_im2col,
                        uint16_t ch_out,
                        uint8_t flag_relu,
                        uint8_t flag_batch_norm)
{

  uint16_t ch_out_r = PACK_INT8_SIZE(ch_out);

  uint16_t num_col_im2col_w = PACK_INT8_SIZE(num_col_im2col);
  uint16_t num_col_im2col_a = PACK_INT8_SIZE(num_col_im2col);

  int32_t a_rollback = 4 - num_col_im2col_a;
  int32_t w_rollback = 4 - (num_col_im2col_w + (num_col_im2col_w << 1));

  LEGACY_MODE("0");
  IVEC_FMT("2");
  A_STRIDE(num_col_im2col_a);
  W_STRIDE(num_col_im2col_w);
  A_ROLLBACK(a_rollback);
  W_ROLLBACK(w_rollback);
  A_SKIP("1");
  W_SKIP("3");
  MIXED_SKIP("8");

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

    for(int j=0; j<(num_col_im2col >> 2); j++)
    {
      ptrB = MacLoadInit(0, 1, 0, 1, ptrB);

      sum  = MacLoad4(0, 0, 0, 0, ptrA, sum);
      sum2 = MacLoad4(0, 0, 1, 0, ptrA, sum2);
      sum3 = MacLoad4(0, 0, 2, 0, ptrA, sum3);
      sum4 = MacLoad4(0, 1, 3, 0, ptrB, sum4);
      ptrB = MacLoadUpdate(ptrB);

      sum5 = MacLoad4(1, 0, 0, 1, ptrA, sum5);
      ptrA = MacLoadUpdate(ptrA);

      sum6 = MacLoad4(1, 0, 1, 1, ptrA, sum6);
      ptrA = MacLoadUpdate(ptrA);

      sum7 = MacLoad4(1, 0, 2, 1, ptrA, sum7);
      ptrA = MacLoadUpdate(ptrA);

      sum8 = MacLoad4(1, 0, 3, 1, ptrA, sum8);
      ptrA = MacLoadUpdate(ptrA);

    }

    
    int col_cnt_im2col = num_col_im2col & 0x3;

    if(col_cnt_im2col)
    {
      uint16_t loop_cnt_im2col_w = (num_col_im2col >> 2) << 2;
      pA+=loop_cnt_im2col_w;

      uint16_t loop_cnt_im2col_a = (num_col_im2col >> 2) << 2;
      
      int8_t *pA2 = (pA  + num_col_im2col_w);
      int8_t *pA3 = (pA2 + num_col_im2col_w);
      int8_t *pA4 = (pA3 + num_col_im2col_w);

      pB+=loop_cnt_im2col_a;
      
      uint8_t *pB2 = (pB + loop_cnt_im2col_a);

      do
      {
        int8_t inA = *pA++;
        int8_t inA2 = *pA2++;
        int8_t inA3 = *pA3++;
        int8_t inA4 = *pA4++;

        uint8_t inB = *pB++;
        uint8_t inB2 = *pB2++;
        asm volatile("": : :"memory");
        sum += inA * inB;
        sum2 += inA2 * inB;
        sum3 += inA3 * inB;
        sum4 += inA4 * inB;

        sum5 += inA * inB2;
        sum6 += inA2 * inB2;
        sum7 += inA3 * inB2;
        sum8 += inA4 * inB2;

        col_cnt_im2col--;
      } while(col_cnt_im2col);
      pA-=num_col_im2col_w;
    }
    if (flag_batch_norm && flag_relu)
    {
      *pOut = pulp_nn_bn_quant_u8(sum, *pKappa, *pLambda, out_shift);
      pOut++;
      *pOut2 = pulp_nn_bn_quant_u8(sum5, *pKappa, *pLambda, out_shift);
      pOut2++;
      pKappa++;
      pLambda++;

      *pOut = pulp_nn_bn_quant_u8(sum2, *pKappa, *pLambda, out_shift);
      pOut++;
      *pOut2 = pulp_nn_bn_quant_u8(sum6, *pKappa, *pLambda, out_shift);
      pOut2++;
      pKappa++;
      pLambda++;

      *pOut = pulp_nn_bn_quant_u8(sum3, *pKappa, *pLambda, out_shift);
      pOut++;
      *pOut2 = pulp_nn_bn_quant_u8(sum7, *pKappa, *pLambda, out_shift);
      pOut2++;
      pKappa++;
      pLambda++;

      *pOut = pulp_nn_bn_quant_u8(sum4, *pKappa, *pLambda, out_shift);
      pOut++;
      *pOut2 = pulp_nn_bn_quant_u8(sum8, *pKappa, *pLambda, out_shift);
      pOut2++;
      pKappa++;
      pLambda++;
    }
    else
    {
      if (flag_relu == 1)
      {
        *pOut = pulp_nn_quant_u8(sum, out_mult, out_shift);
        pOut++;
        *pOut = pulp_nn_quant_u8(sum2, out_mult, out_shift);
        pOut++;
        *pOut = pulp_nn_quant_u8(sum3, out_mult, out_shift);
        pOut++;
        *pOut = pulp_nn_quant_u8(sum4, out_mult, out_shift);
        pOut++;

        *pOut2 = pulp_nn_quant_u8(sum5, out_mult, out_shift);
        pOut2++;
        *pOut2 = pulp_nn_quant_u8(sum6, out_mult, out_shift);
        pOut2++;
        *pOut2 = pulp_nn_quant_u8(sum7, out_mult, out_shift);
        pOut2++;
        *pOut2 = pulp_nn_quant_u8(sum8, out_mult, out_shift);
        pOut2++;

      }
      else
      {
        *pOut = (uint8_t) clip8(sum >> out_shift);
        pOut++;
        *pOut = (uint8_t) clip8(sum2 >> out_shift);
        pOut++;
        *pOut = (uint8_t) clip8(sum3 >> out_shift);
        pOut++;
        *pOut = (uint8_t) clip8(sum4 >> out_shift);
        pOut++;

        *pOut2 = (uint8_t) clip8(sum5 >> out_shift);
        pOut2++;
        *pOut2 = (uint8_t) clip8(sum6 >> out_shift);
        pOut2++;
        *pOut2 = (uint8_t) clip8(sum7 >> out_shift);
        pOut2++;
        *pOut2 = (uint8_t) clip8(sum8 >> out_shift);
        pOut2++;

      }
    }
    pA+=(4 * num_col_im2col_w);
  }

  w_rollback = 4;
  W_ROLLBACK(w_rollback);
  W_SKIP("0");
  MIXED_SKIP("2");

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

    for(int j=0; j < (num_col_im2col >> 2); j++)
    {
      ptrB = MacLoadInit(0, 1, 0, 1, ptrB);

      sum  = MacLoad4(0, 1, 0, 0, ptrB, sum);
      ptrB = MacLoadUpdate(ptrB);

      sum2 = MacLoad4(1, 0, 0, 1, ptrA, sum2);
      ptrA = MacLoadUpdate(ptrA);
    }
    int col_cnt_im2col = num_col_im2col & 0x3;

    if(col_cnt_im2col)
    {
      uint16_t loop_cnt_im2col_w = (num_col_im2col >> 2) << 2;
      pA+=loop_cnt_im2col_w;

      uint16_t loop_cnt_im2col_a = (num_col_im2col >> 2) << 2;
      pB+=loop_cnt_im2col_a;
      
      uint8_t *pB2 = (pB +loop_cnt_im2col_a);

      int8_t *pA2 = (pA  + num_col_im2col_w);
      int8_t *pA3 = (pA2 + num_col_im2col_w);
      int8_t *pA4 = (pA3 + num_col_im2col_w);

      do
      {
        int8_t inA = *pA++;

        uint8_t inB = *pB++;
        uint8_t inB2 = *pB2++;
        asm volatile("": : :"memory");
        sum += inA * inB;

        sum2 += inA * inB2;

        col_cnt_im2col--;
      } while(col_cnt_im2col);
      pA-=num_col_im2col_w;
    }
    if (flag_batch_norm && flag_relu)
    {
      *pOut = pulp_nn_bn_quant_u8(sum, *pKappa, *pLambda, out_shift);
      pOut++;
      *pOut2 = pulp_nn_bn_quant_u8(sum2, *pKappa, *pLambda, out_shift);
      pOut2++;
      pKappa++;
      pLambda++;
    }
    else
    {
      if (flag_relu == 1)
      {
        *pOut = pulp_nn_quant_u8(sum, out_mult, out_shift);
        pOut++;
        *pOut2 = pulp_nn_quant_u8(sum2, out_mult, out_shift);
        pOut2++;
      }
      else
      {
        *pOut = (uint8_t) clip8(sum >> out_shift);
        pOut++;
        *pOut2 = (uint8_t) clip8(sum2 >> out_shift);
        pOut2++;
      }
    }
    pA+=num_col_im2col_w;
    chan_left--;
  }
  pOut+=ch_out_r;
  return pOut;
}
