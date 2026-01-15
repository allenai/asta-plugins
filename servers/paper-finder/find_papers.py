#!/usr/bin/env python3
"""CLI for background paper searches. Results saved to ~/.asta/widgets/"""

import argparse
import json

from asta_paper_finder import AstaPaperFinder

parser = argparse.ArgumentParser()
parser.add_argument("query")
parser.add_argument("--timeout", type=int, default=300)
args = parser.parse_args()

result = AstaPaperFinder().find_papers(args.query, args.timeout)
print(json.dumps(result, indent=2))
