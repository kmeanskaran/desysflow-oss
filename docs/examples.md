# Examples

## Basic Local Design Generation

```bash
./letsvibedesign cli
```

Or run the command directly:

```bash
desysflow design --source . --out ./desysflow --project ecommerce-system
```

## Focused Refinement

```bash
desysflow redesign \
  --source . \
  --out ./desysflow \
  --project ecommerce-system \
  --focus "optimize checkout scalability and caching"
```

## Run API + UI Together

```bash
./letsvibedesign dev
```

## Run API Only

```bash
./letsvibedesign api
```

## Run UI Only

```bash
./letsvibedesign ui
```

UI only expects the API to already be running, usually with `./letsvibedesign api`.

## Validate Provider/Model

```bash
./letsvibedesign check
```

## Generate with Explicit Options

```bash
desysflow design \
  --source . \
  --out ./desysflow \
  --project ecommerce-system \
  --model-provider ollama \
  --model gpt-oss:20b-cloud \
  --language python \
  --cloud aws \
  --style detailed \
  --web-search auto \
  --no-interactive
```
