import torch
import warpctc_pytorch as warp_ctc
from torch.autograd import Function, Variable
from torch.nn import Module
from torch.nn.modules.loss import _assert_no_grad
from torch.utils.ffi import _wrap_function
from ._warp_ctc import lib as _lib, ffi as _ffi

__all__ = []


def _import_symbols(locals):
    for symbol in dir(_lib):
        fn = getattr(_lib, symbol)
        locals[symbol] = _wrap_function(fn, _ffi)
        __all__.append(symbol)


_import_symbols(locals())


class _CTC(Function):
    @staticmethod
    def forward(ctx, acts, labels, act_lens, label_lens):
        is_cuda = True if acts.is_cuda else False
        acts = acts.contiguous()
        loss_func = warp_ctc.gpu_ctc if is_cuda else warp_ctc.cpu_ctc
        grads = torch.zeros(acts.size()).type_as(acts)
        minibatch_size = acts.size(1)
        costs = torch.zeros(minibatch_size).cpu()
        loss_func(acts,
                  grads,
                  labels,
                  label_lens,
                  act_lens,
                  minibatch_size,
                  costs)
        ctx.grads = Variable(grads)
        if is_cuda:
            ctx.costs = costs.cuda(acts.get_device())
        else:
            ctx.costs = costs
        return ctx.costs

    @staticmethod
    def backward(ctx, grad_output):
        if grad_output.is_cuda:
            ctx.grads = ctx.grads.cuda(grad_output.get_device())
        return grad_output.contiguous().view(1, -1, 1) * ctx.grads, None, None, None


class CTCLoss(Module):
    def __init__(self):
        super(CTCLoss, self).__init__()

    def forward(self, acts, labels, act_lens, label_lens, reduce=True):
        """
        acts: Tensor of (seqLength x batch x outputDim) containing output from network
        labels: 1 dimensional Tensor containing all the targets of the batch in one sequence
        act_lens: Tensor of size (batch) containing size of each output sequence from the network
        act_lens: Tensor of (batch) containing label length of each example
        """
        assert len(labels.size()) == 1 # labels must be 1 dimensional
        _assert_no_grad(labels)
        _assert_no_grad(act_lens)
        _assert_no_grad(label_lens)
        costs = _CTC.apply(acts, labels, act_lens, label_lens)
        if reduce:
            return costs.sum()
        else:
            return costs
