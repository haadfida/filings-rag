# filings-rag

Question answering over company filings, with a page citation for every figure. Measured on the
FinanceBench open set; the design and the reasoning behind it are in [DESIGN.md](DESIGN.md).

Status: milestone 5 done (retrieval recall). Results: [milestone 1](results/milestone-1/RESULTS.md), [milestone 2](results/milestone-2/RESULTS.md), [milestone 3](results/milestone-3/RESULTS.md), [milestone 4](results/milestone-4/RESULTS.md), [milestone 5](results/milestone-5/RESULTS.md).

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # macOS/Linux: .venv/bin/python
.venv/Scripts/filings-rag data                    # downloads 2 data files and 84 PDFs, then verifies them
.venv/Scripts/filings-rag stats
.venv/Scripts/python -m pytest
```

`filings-rag data` fetches the benchmark from `patronus-ai/financebench` at a pinned commit, records a
SHA-256 for every file in `data/financebench/manifest.json`, and checks that each PDF opens and contains
every evidence page. Re-running skips files that already match.

## Data and licence

The questions and filings are not in this repository. They are downloaded from the FinanceBench
repository, and the Hugging Face copy of the dataset is licensed
[CC BY-NC 4.0](https://huggingface.co/datasets/PatronusAI/financebench). This project is noncommercial.

> Islam, P., Kannappan, A., Kiela, D., Qian, R., Scherrer, N., and Vidgen, B. (2023).
> FinanceBench: A New Benchmark for Financial Question Answering. arXiv:2311.11944.

Three reference answers contradict their own worked justification; they are listed in
`src/filings_rag/benchmark.py` and scores are reported with and without them.
