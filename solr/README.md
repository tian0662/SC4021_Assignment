# 3.2 Indexing (Solr)

This folder contains a minimal reproducible pipeline for the SC4021 indexing task.

## 1) Start Solr

```bash
docker run -d --name sc4021-solr -p 8983:8983 solr:9 solr-precreate reddit_ai
```

## 2) Create / update schema fields

```bash
curl -X POST -H 'Content-type:application/json' \
  http://localhost:8983/solr/reddit_ai/schema \
  --data-binary '{
    "add-field": [
      {"name":"id","type":"string","stored":true,"indexed":true,"required":true},
      {"name":"type","type":"string","stored":true,"indexed":true},
      {"name":"title","type":"text_en","stored":true,"indexed":true},
      {"name":"body","type":"text_en","stored":true,"indexed":true},
      {"name":"full_text","type":"text_en","stored":true,"indexed":true},
      {"name":"subreddit","type":"string","stored":true,"indexed":true},
      {"name":"score","type":"pint","stored":true,"indexed":true},
      {"name":"created_date","type":"pdate","stored":true,"indexed":true},
      {"name":"thread_id","type":"string","stored":true,"indexed":true},
      {"name":"source_file","type":"string","stored":true,"indexed":true}
    ]
  }'
```

> If fields already exist, Solr may return an error; this is safe to ignore.

## 3) Build JSONL docs from 3.1 crawling outputs

```bash
python scripts/prepare_solr_docs.py --output data/reddit_docs.jsonl
```

## 4) Index data into Solr

```bash
curl -X POST -H 'Content-type:application/json' \
  'http://localhost:8983/solr/reddit_ai/update?commit=true' \
  --data-binary @data/reddit_docs.jsonl
```

## 5) Run UI

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

## 6) Benchmark five required queries

```bash
python scripts/benchmark_queries.py
```

