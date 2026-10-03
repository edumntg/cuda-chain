# CIFAR-10

A 0.8M-parameter convolutional network on 50,000 colour images of 32×32 pixels in 10
classes (airplane, automobile, bird, cat, deer, dog, frog, horse, ship, truck). The job
takes minutes, so it shows what two machines do that one cannot.

| File | What it is |
|---|---|
| `job.yaml` | the job: any number of trainers, 30 rounds |
| `benchmark-one-trainer.yaml` | the same job, `max_trainers: 1` |
| `benchmark-two-trainers.yaml` | the same job, exactly two trainers per round |
| `eval.py` | accuracy of a downloaded model on the 10,000 test images |

The person who submits downloads the archive once (163 MB, MD5 checked). The job holds
20 shards of 2,500 images on the server; a trainer fetches one shard per round.

```bash
plasmon job submit examples/cifar10/job.yaml
plasmon job watch <id>
plasmon job download <id> -o cifar.safetensors
python3 examples/cifar10/eval.py cifar.safetensors
```

## What to expect

Each round, every trainer runs 100 steps of batch 64 on its shard (6,400 images) and
sends a compressed update. The server averages the updates and applies the outer step.
Times per round, measured on CPU only:

| Machine | Time per round |
|---|---|
| Apple silicon, MPS | about 10 s |
| A recent x86 laptop, CPU | 15 to 30 s |
| An old 4-thread CPU | about 70 s |

Accuracy after 30 rounds with one trainer is about 55 to 60 %. With `width: 16` in
`model.config` the network has a quarter of the compute; use it on slow CPUs.

## One trainer or two: how to compare

Rounds are synchronous: the server waits for every trainer of the round, so a round takes
as long as the slowest machine. Two machines do not make a round faster. What they change
is how much data each round learns from: two shards instead of one, averaged. The honest
comparison is the model you get for the same number of rounds, and the wall-clock time it
took.

1. Start the trainers on both machines. Check both are `idle` with `plasmon fleet`.
2. Submit `benchmark-one-trainer.yaml`. Note the time; `plasmon job status <id>` shows
   `finished_at - created_at` through the API, and the job page shows the per-round times.
3. Submit `benchmark-two-trainers.yaml`. Both machines take every round.
4. Compare: eval accuracy at round 30 (job page or `eval.py`), total time, time per round.

Expected: the two-trainer job reaches a higher accuracy at the same round count (it saw
twice the images per round), with rounds that take about the time of the slower machine.
If one machine is much slower than the other, the one-trainer job on the fast machine
can finish first; DiLoCo rewards similar machines, and `max_trainers` with a GPU-only
`device: cuda` is how you keep slow machines out of a job.
