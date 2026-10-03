# Shakespeare, a character-level language model

A causal transformer (4 layers, 128-wide, 4 heads, 0.8M parameters) that predicts the
next character of Shakespeare's plays. It is the same family of model as a large language
model, about a thousand times smaller, and it trains on a CPU.

```bash
plasmon job submit examples/shakespeare/job.yaml
plasmon job watch <id>
plasmon job download <id> -o shakespeare.safetensors
python3 examples/shakespeare/sample.py shakespeare.safetensors --prompt "ROMEO:" --length 400
```

The text (1.1 MB) is downloaded once by the person who submits and cut into sequences of
128 characters. The eval loss on the job page is in nats per character: 4.85 is a model
that knows nothing (ln 128); a trained model of this size reaches about 1.5 to 1.7, and
the samples read like Elizabethan English with invented words.

Each round is 40 steps of 16 sequences. Time per round: about 3 s on Apple silicon, 5 to
10 s on a recent x86 CPU. Two trainers give each round twice the text.

The accuracy column means next-character accuracy.
