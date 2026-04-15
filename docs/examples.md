# Examples

## Basic Local Design Generation

```bash
letsvibedesign cli
```

Then keep working from the `letsvibe>` prompt with `run`, `design <prompt>`, `restart`, or `bye`.

Or run the command directly:

```bash
desysflow design --source . --out ./.desysflow --project ecommerce-system
```

## Focused Refinement

```bash
desysflow redesign \
  --source . \
  --out ./.desysflow \
  --project ecommerce-system \
  --focus "optimize checkout scalability and caching"
```

## Run API + UI Together

```bash
letsvibedesign dev
```

## Generate with Explicit Options

```bash
desysflow design \
  --source . \
  --out ./.desysflow \
  --project ecommerce-system \
  --model-provider ollama \
  --model gpt-oss:20b-cloud \
  --language python \
  --cloud aws \
  --style detailed \
  --web-search auto \
  --no-interactive
```
