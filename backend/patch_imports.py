with open("app/workers/pipeline.py", encoding="utf-8") as f:
    text = f.read()

# Pull out any imports that precede from __future__
lines = text.split("\n")
futures = [l for l in lines if l.startswith("from __future__")]
non_futures = [l for l in filter(lambda x: not x.startswith("from __future__"), lines)]

with open("app/workers/pipeline.py", "w", encoding="utf-8") as f:
    f.write("\n".join(futures) + "\n" + "\n".join(non_futures))
