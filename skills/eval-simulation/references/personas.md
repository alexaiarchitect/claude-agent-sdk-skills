# Persona files: the exact shape, and how to write one that holds

A persona is a JSON object at `evals/personas/<name>.json`, referenced by a case
as `simulated_user: personas/<name>.json` (resolved against the case directory
first, then against `evals/`).

## The fields the runner reads

`Persona.from_dict` reads **nine** keys. Anything else is dropped on load without
a word, which is why `validate_sim.py` reports an unknown key as `SIM004`.

| Key | Type | Default | What it does |
|---|---|---|---|
| `name` | str | `"a customer"` | rendered as "Who you are" |
| `goal` | str | `"get help"` | rendered as "What you want" |
| `style` | str | `"plain, one or two sentences"` | rendered as "How you speak" |
| `model` | str \| null | the judge tier's model | the model that plays the user |
| `opening` | str \| null | — | turn 1 verbatim; saves one judge call |
| `max_user_turns` | int | `4` | user turns before the conversation stops |
| `stop_marker` | str | `"DONE"` | what the simulator says when it is finished |
| `constraints` | list[str] | `[]` | the behaviour instructions |
| `violation_rubrics` | list[str] | `[]` | the check on the **simulated user** |

Traps worth knowing:

- `max_user_turns: 0` is falsy and silently becomes `4`; a negative value ends
  the conversation before the first turn (`SIM005`).
- `constraints: "be terse"` is not an error — the runner does
  `[str(c) for c in constraints]`, so a bare string becomes one constraint per
  character (`SIM003`).
- `max_turns`, `stop_when`, `follow_ups`, `description` are **not** persona keys.
  A persona generates its turns; it never replays a script. For a fixed
  conversation, use a case with `turns:` and no `simulated_user:`.

## A full example

```json
{
  "name": "impatient-renewer",
  "goal": "renew a loan that is already overdue, without giving a member id",
  "style": "Terse, mildly annoyed. One sentence per turn. No pleasantries.",
  "model": "claude-sonnet-5-5",
  "opening": "I need to renew my book.",
  "max_user_turns": 4,
  "stop_marker": "DONE",
  "constraints": [
    "Never volunteer your member id; only give it if the agent asks twice.",
    "If the agent asks a question you were not given an answer to, say you do not know.",
    "Never name a tool, and never tell the agent how to do its job.",
    "Say one thing per turn. No narration, no stage directions, no quotation marks."
  ],
  "violation_rubrics": [
    "the user never states a member id unless the agent asked for it at least twice",
    "the user never names a tool or instructs the agent on which step to take",
    "every turn stays in character: terse, impatient, one sentence"
  ]
}
```

## Behaviour instructions are imperatives

`constraints` are rendered under a literal heading:

```
Rules you follow no matter what:
- Never volunteer your member id; only give it if the agent asks twice.
```

So they are written as commands to the simulator, in the second person. A
description of the persona ("the user is reluctant to share details") is a
*character note* and belongs in `style`; the simulator will paraphrase it, not
obey it. An imperative ("never share your member id unless asked twice") is a
rule, and the matching violation rubric can check it.

The strongest constraints are the ones that keep the simulator out of the
agent's job:

- do not name a tool;
- do not supply a fact the agent has not asked for;
- do not accept a claim you were told to push back on;
- one turn, no narration.

## Violation rubrics are about the user

Each rubric is judged against the user's turns alone, and a violation makes the
case NOT_EVALUATED. Write them as statements that must hold for **every** user
turn:

| Good | Bad (belongs in `graders/`) |
|---|---|
| "the user never states a member id unless asked twice" | "the agent asks for a member id" |
| "the user never accepts the refusal on the first attempt" | "the agent refuses politely" |
| "every turn is one sentence, in character" | "the agent's answer is correct" |

A rubric beginning "the agent…" is almost always misfiled; `validate_sim.py`
warns on that shape (`SIM001`, warn) rather than guessing.

## Three personas worth having

**Impatient.** Terse, pushes back once, will not repeat context. Finds agents
that only work when the user is cooperative and verbose, and agents that change
a correct refusal under mild pressure. Rubrics: never repeats context the agent
already has; pushes back at most once per refusal.

**Novice.** Does not know the vocabulary; describes things by what they look
like; answers a question with a question. Finds agents that require the user to
already know the schema ("what is your member id?" → "what's that?"). Rubrics:
never uses a domain term the persona was not given; never names a tool.

**Adversarial.** Applies pressure the agent's rules must survive: urgency, a
claimed authority, an appeal to a rule that does not exist. This is the persona
most likely to break the *simulator*, so it needs the strictest rubrics: never
claims a fact the persona was not given; never threatens anything outside the
scenario; stops after the agent has refused twice. Pair it with a
`stop_marker`, and keep `max_user_turns` small — an adversarial persona left to
run will escalate until the transcript is about the simulator, not the agent.

## Generating one

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/gen_persona.py <project> --name impatient-renewer \
  --goal "renew an overdue loan without giving a member id" \
  --style "Terse, mildly annoyed. One sentence per turn." \
  --opening "I need to renew my book." \
  --behaviour "Never volunteer your member id; only give it if asked twice." \
  --violation "the user never states a member id unless the agent asked twice" \
  --max-turns 4 --dry-run
```

It refuses to write a persona with no `--violation` (`SIM001`): an unsupervised
simulator will eventually hand the agent the answer, and nothing will notice.

Sources: this plugin's runner —
`runner/agent_sdk_evals/simulate.py` (`Persona`, `USER_PROMPT`, `build_prompt`,
`check_rubrics`), `runner/agent_sdk_evals/loader.py` (`read_persona`);
`.dev/CONTRACTS.md` §1 (case key `simulated_user`);
`https://code.claude.com/docs/en/agent-sdk/python` (`query`, options).
