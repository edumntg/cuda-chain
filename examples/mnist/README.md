# MNIST examples

Four job files that train the same small CNN. They differ only in where the data comes
from. Submit any of them with `plasmon job submit <file>`, or paste the text into
**Jobs**, **Submit a job** on the dashboard.

| File | Data source | Download | Size |
|---|---|---|---|
| `job.yaml` | `builtin://mnist` | automatic, from a public mirror | 11 MB |
| `job-fashion.yaml` | `builtin://fashion-mnist` | automatic, from the Zalando Research repository on GitHub | 30 MB |
| `job-csv.yaml` | MNIST as CSV at public URLs | automatic, cached after the first run | 110 MB + 18 MB |
| `job-local.yaml` | a folder with the MNIST files you downloaded yourself | manual, see below | 11 MB |

The person who submits the job downloads the data once. The job then holds it as shards
on the server, and each trainer fetches only the shard it is assigned.

## The public files

MNIST, the four original files. The example uses the mirror PyTorch uses:

```bash
mkdir -p ~/mnist && cd ~/mnist
curl -fsSLO https://ossci-datasets.s3.amazonaws.com/mnist/train-images-idx3-ubyte.gz
curl -fsSLO https://ossci-datasets.s3.amazonaws.com/mnist/train-labels-idx1-ubyte.gz
curl -fsSLO https://ossci-datasets.s3.amazonaws.com/mnist/t10k-images-idx3-ubyte.gz
curl -fsSLO https://ossci-datasets.s3.amazonaws.com/mnist/t10k-labels-idx1-ubyte.gz
```

A second mirror has the same files: `https://storage.googleapis.com/cvdf-datasets/mnist/`.

MNIST as CSV, one image per row, the label first, then 784 pixels:

- `https://pjreddie.com/media/files/mnist_train.csv` (60,000 rows, 110 MB)
- `https://pjreddie.com/media/files/mnist_test.csv` (10,000 rows, 18 MB)

Fashion-MNIST, the same four file names, from
`https://raw.githubusercontent.com/zalandoresearch/fashion-mnist/master/data/fashion/`.

## Point a job at your own copy

`job-local.yaml` uses the folder from the `curl` commands above:

```yaml
dataset:
  source: ~/mnist          # the four .gz files; the test files are optional
```

A CSV you downloaded works the same way:

```yaml
dataset:
  source: ~/mnist/mnist_train.csv
  eval_source: ~/mnist/mnist_test.csv     # optional; without it, eval_fraction of the rows is held out
  label_column: first                     # or last
```

A `.npz` with arrays `x` (N×28×28, uint8) and `y` (N, uint8) also works, as a file or as
a folder of files.

## What to expect

With `examples/mnist/job.yaml` and two CPUs, twenty rounds take two to four minutes and
reach 96 % to 98 % on the 10,000 test images:

```bash
plasmon job download <id> -o mnist.safetensors
python3 examples/mnist/eval.py mnist.safetensors
```

`eval.py` measures on the MNIST test set. For Fashion-MNIST, pass `--dataset fashion-mnist`.
