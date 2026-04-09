# I vibe coded an AI-native system design platform, and today I am open sourcing it

Most codebases can run.

Very few can explain themselves.

That is the gap I kept seeing again and again.

A repo grows fast. Features ship. Infra gets patched. New services appear. Queues get added. Caching gets introduced. Retries show up after the first production scare. The system becomes real, but the design story becomes blurry. New engineers need hours to understand it. Founders struggle to present it clearly. Consultants rebuild the same mental model from scratch. Product teams ask for architecture docs that nobody has time to write.

So I built DesysFlow OSS.

DesysFlow OSS is an AI-native, open source, local-first system design platform that turns real source code into versioned architecture artifacts. You point it at a codebase, describe what you want, and it generates structured outputs like HLD, LLD, technical reports, non-technical summaries, Mermaid diagrams, and version diffs.

I vibe coded it because I wanted a tool that felt modern, fast, practical, and actually useful in real engineering work. Not a toy demo. Not a chat box that gives you one long answer and then forgets everything. A real workflow.

This is my launch story, but more importantly, this is a tool built for anyone who has ever thought:

"This system works, but explaining it is harder than building it."

## What problem DesysFlow solves

DesysFlow solves a very boring but very expensive problem.

Architecture understanding is usually trapped in three places:

- the code
- the heads of a few people
- stale Markdown files no one trusts anymore

That creates friction everywhere.

- onboarding gets slower
- architecture reviews become messy
- system redesign discussions start from confusion
- technical writing becomes a chore
- non technical stakeholders stay out of the loop

DesysFlow takes that hidden architecture knowledge and turns it into something teams can actually use.

It reads the repository, builds context from the codebase, runs a multi-agent workflow, and writes structured outputs into versioned folders. That means you do not just get a generated answer. You get artifact management that fits how teams already work.

## What I mean by AI-native

I call DesysFlow AI-native because AI is not glued on top as a gimmick.

The product is designed around AI as the engine for understanding, synthesis, refinement, and documentation.

But it is grounded in software workflow, not hype.

That means:

- source code is the main input
- generated outputs are saved as files
- every run creates versioned artifacts
- CLI and UI both support the same design flow
- refinement is built into the workflow
- local model support exists through Ollama
- open models and hosted models are both supported

So yes, this was vibe coded, but it was vibe coded with structure.

I wanted the speed of AI-assisted building without sacrificing the discipline of outputs that engineers can inspect, diff, and improve.

## What it generates

DesysFlow writes design artifacts into versioned project folders like:

```text
desysflow/<project>/v1/
desysflow/<project>/v2/
```

Inside those folders, you get outputs such as:

- `HLD.md`
- `LLD.md`
- `TECHNICAL_REPORT.md`
- `NON_TECHNICAL_DOC.md`
- `diagram.mmd`
- `DIFF.md`
- `METADATA.json`

This part matters a lot to me.

I did not want architecture generation to end as one disposable response in a terminal. I wanted `.md` management to feel first class. Teams already live in Markdown for docs, reviews, and handoffs. So DesysFlow makes Markdown outputs part of the product, not an afterthought.

That means your architecture can evolve like your code evolves.

You can compare versions. Review diffs. Share artifacts. Keep a historical trail. Re-run with a new prompt. Refine a previous direction. Build a habit around living system design docs.

## The multi-agent system behind it

Under the hood, DesysFlow uses a multi-agent workflow to break the task into more useful steps instead of trying to brute force everything in one prompt.

At a high level, the flow handles:

- requirement extraction
- template selection
- architecture generation
- edge case injection
- architecture selection
- diagram generation
- diagram quality review
- report generation
- cloud infrastructure planning

That matters because good system design is not one thing.

It is understanding.
It is reasoning.
It is tradeoff analysis.
It is communication.
It is visual explanation.

By splitting the workflow into specialized stages, DesysFlow produces outputs that are more structured and easier to review.

There is also support for follow-up refinement and additional critic loops on the API side, which makes the platform more useful for iterative design work instead of one-shot generation.

## Why this is special

There are many AI tools right now. Most look impressive for five minutes. Very few become part of an actual engineering workflow.

I think DesysFlow is special for a few precise reasons:

- It is open source. You can inspect everything, modify it, and contribute to it.
- It is local-first. Your repo and outputs stay close to your environment.
- It supports both CLI and UI. Terminal-first people and visual-first people can both use it.
- It creates versioned artifacts, not throwaway responses.
- It treats Markdown as a real output format for teams.
- It supports Ollama, OpenAI, and Anthropic.
- It includes guardrails for secret leak detection on LLM output.
- It is built around real codebases, not synthetic demo prompts.

For me, the strongest differentiator is this:

DesysFlow is not trying to replace engineering thinking.

It is trying to accelerate engineering understanding.

That is a much better product philosophy.

## How to install it

If you want to try it right away, here is the simplest path.

Clone the repo:

```bash
git clone <your-repo-url>
cd desysflow-oss
```

Run the bootstrap setup:

```bash
./letsvibedesign
```

This will:

- create `.venv`
- install Python dependencies
- install UI dependencies
- ask for your model provider and model
- write local configuration to `.env.example`
- validate model availability

You can use:

- `ollama`
- `openai`
- `anthropic`

If you want the most local experience, start with Ollama.

## How to run the CLI

Launch the CLI with:

```bash
./letsvibedesign cli
```

This opens a persistent CLI loop. After each run, it returns to a `letsvibe>` prompt so you can continue exploring without restarting.

That small detail makes the product feel much better in practice.

You can run a design prompt like this:

```text
/design design a scalable ecommerce backend with payments, inventory, notifications, and admin reporting
```

Or just type plain text at the prompt and DesysFlow treats it as your design request.

Useful loop commands:

```text
run
/design
/design <prompt>
/restart
/bye
```

Suggested screenshot:

`[Add CLI screenshot here showing letsvibe prompt, stage logs, and generated artifact path]`

The CLI also shows clear progress logs with labeled stages and completion updates, which makes it easier to understand what the system is doing during generation.

## How to run the UI

If you want the full local app experience, run:

```bash
./letsvibedesign dev
```

Then open:

- `http://localhost:5173` for the UI
- `http://localhost:8000/docs` for the API docs

From the UI, you can:

- open model settings
- choose provider and model
- add API keys when needed
- check model status
- enter a design prompt
- refine the design with follow-up prompts

Suggested screenshot:

`[Add UI screenshot here showing prompt box, model settings, and generated design outputs]`

This is important for Product Hunt readers because not everyone wants to start in the terminal. The UI makes DesysFlow easier to demo, easier to share, and easier to understand quickly.

## Who this is for

DesysFlow OSS is useful if you are:

- a founder trying to explain your product architecture clearly
- an engineer joining a large or messy repo
- a consultant auditing an existing system
- a team preparing design reviews
- a builder who wants living architecture docs
- an open source contributor who wants to extend AI-native developer tooling

If your codebase is the truth but your docs are weak, this is for you.

## The bigger idea

I think we are entering a phase where software tools will not just help us write code. They will help us understand code, explain code, review code, and transform code into team knowledge.

That is the category I want DesysFlow to live in.

Not just "AI for architecture."

More like:

AI-native design infrastructure for real software teams.

Open source matters here because the best developer tools often grow through community feedback, real-world edge cases, and people adapting them to workflows the original builder did not predict.

## Contribute to DesysFlow OSS

This is where I need the community.

If this project resonates with you, contribute.

You can help by:

- testing it on your codebase
- opening issues
- improving prompts and agent behavior
- improving docs and examples
- extending the UI
- improving output quality
- adding new workflows and integrations

If you care about open source AI tools that are practical, inspectable, and useful for real engineering work, I would love your help shaping this.

## Final note

I built DesysFlow OSS because system design should not disappear into memory, meetings, or stale docs.

Your codebase already knows the architecture.

Now it can explain it.

Try it, break it, improve it, and contribute to it.

```bash
git clone <your-repo-url>
cd desysflow-oss
./letsvibedesign
./letsvibedesign cli
```

Or if you want the visual flow:

```bash
./letsvibedesign dev
```

DesysFlow OSS is now open source.

I am excited to see what builders do with it.
