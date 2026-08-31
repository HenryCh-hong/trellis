"""The canonical skill and research-topic vocabularies.

Two jobs:

* keep one spelling of every skill so a profile, a resume and a posting can be
  compared at all (``sklearn``/``scikit learn``/``scikit-learn`` are one thing);
* recognise those skills in prose *without* false positives, because a wrongly
  claimed skill becomes a wrongly claimed strength in the UI.

The second point is why matching goes through
:func:`app.services.text.find_phrase` rather than a substring test, and why
one- and two-character aliases (``R``, ``ML``, ``AI``) only match when they
appear in upper case in the original text: lower-case ``ml`` inside ordinary
prose is almost never the student's skill, while ``ML`` almost always is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT
from app.models.user import ResearchTopic, Skill
from app.services.text import find_phrase, fuzzy_ratio, normalize, phrase_snippet

TOPIC_ONTOLOGY_PATH = REPO_ROOT / "data" / "harvest" / "recon" / "topic-ontology.json"

SKILL_CATEGORIES = ("language", "framework", "tool", "domain", "method", "soft", "service")


@dataclass(frozen=True, slots=True)
class SkillDef:
    slug: str
    label: str
    category: str
    aliases: tuple[str, ...] = ()
    # Some labels are unusable as search terms on their own ("C", "Go").
    match_label: bool = True
    # Phrases that, seen next to a hit, mean it was not the skill after all.
    veto: tuple[str, ...] = ()

    @property
    def terms(self) -> tuple[str, ...]:
        seen: list[str] = []
        for term in ((self.label,) if self.match_label else ()) + self.aliases:
            cleaned = term.strip()
            if cleaned and cleaned.lower() not in {s.lower() for s in seen}:
                seen.append(cleaned)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class TopicDef:
    slug: str
    label: str
    parent: str | None = None
    aliases: tuple[str, ...] = ()
    description: str | None = None


def _s(
    slug: str,
    label: str,
    category: str,
    *aliases: str,
    match_label: bool = True,
    veto: tuple[str, ...] = (),
) -> SkillDef:
    return SkillDef(slug, label, category, tuple(aliases), match_label, veto)


SKILLS: tuple[SkillDef, ...] = (
    # ---------------------------------------------------------- languages
    _s("python", "Python", "language", "python3", "cpython"),
    _s("c++", "C++", "language", "cpp", "c plus plus"),
    _s("c", "C", "language", "c programming", "c language", "ansi c", match_label=False),
    _s("java", "Java", "language"),
    _s("javascript", "JavaScript", "language", "ecmascript", "vanilla js"),
    _s("typescript", "TypeScript", "language"),
    _s("r", "R", "language", "r language", "r programming", "rstudio", veto=("r&d", "r & d")),
    _s("matlab", "MATLAB", "language", "simulink"),
    _s("julia", "Julia", "language", "julia lang"),
    _s("sql", "SQL", "language", "sql queries", "structured query language"),
    _s("bash", "Bash", "language", "shell scripting", "shell script", "zsh", "command line"),
    _s("html-css", "HTML/CSS", "language", "html", "css", "scss"),
    _s("swift", "Swift", "language", "swiftui"),
    _s("go", "Go", "language", "golang", match_label=False),
    _s("rust", "Rust", "language"),
    _s("scala", "Scala", "language"),
    _s("verilog", "Verilog", "language", "systemverilog", "vhdl"),
    _s("assembly", "Assembly", "language", "x86 assembly", "risc-v assembly"),
    _s("latex", "LaTeX", "tool", "overleaf", "bibtex"),
    # --------------------------------------------------------- frameworks
    _s("pytorch", "PyTorch", "framework", "torch", "pytorch lightning"),
    _s("tensorflow", "TensorFlow", "framework", "keras"),
    _s("jax", "JAX", "framework", "flax", "haiku library"),
    _s("react", "React", "framework", "react.js", "reactjs"),
    _s("nextjs", "Next.js", "framework", "nextjs", "next js"),
    _s("nodejs", "Node.js", "framework", "nodejs", "express.js"),
    _s("django", "Django", "framework"),
    _s("flask", "Flask", "framework", "fastapi"),
    _s("numpy", "NumPy", "framework", "scipy"),
    _s("pandas", "pandas", "framework", "dataframes"),
    _s("scikit-learn", "scikit-learn", "framework", "sklearn", "scikit learn"),
    _s("huggingface", "Hugging Face", "framework", "huggingface", "hf hub"),
    _s("transformers", "Transformers", "method", "transformer architecture", "attention mechanism"),
    _s("ros", "ROS", "framework", "ros2", "robot operating system"),
    _s("opencv", "OpenCV", "framework"),
    _s("mujoco", "MuJoCo", "framework", "isaac gym", "isaac sim", "pybullet"),
    _s("unity", "Unity", "tool", "unity3d", "unreal engine"),
    _s("blender", "Blender", "tool"),
    _s("tailwind", "Tailwind CSS", "framework", "tailwindcss"),
    _s("spark", "Apache Spark", "framework", "pyspark"),
    # -------------------------------------------------------------- tools
    _s("git", "Git", "tool", "github", "version control", "gitlab"),
    _s("linux", "Linux", "tool", "unix", "ubuntu"),
    _s("docker", "Docker", "tool", "containerization", "containerisation"),
    _s("aws", "AWS", "tool", "amazon web services", "ec2", "s3 bucket"),
    _s("gcp", "Google Cloud", "tool", "gcp", "google cloud platform", "bigquery"),
    _s("kubernetes", "Kubernetes", "tool", "k8s"),
    _s("slurm", "Slurm", "tool", "hpc cluster", "compute cluster", "sherlock cluster"),
    _s("jupyter", "Jupyter", "tool", "jupyter notebook", "google colab", "colab"),
    _s("figma", "Figma", "tool", "sketch app"),
    _s("tableau", "Tableau", "tool", "power bi"),
    _s("excel", "Excel", "tool", "microsoft excel", "spreadsheets", "spreadsheet"),
    _s(
        "microsoft-office",
        "Microsoft Office",
        "tool",
        "ms office",
        "word processing",
        "powerpoint",
        "outlook",
    ),
    _s(
        "google-workspace",
        "Google Workspace",
        "tool",
        "google docs",
        "google sheets",
        "gsuite",
        "g suite",
    ),
    _s("canvas-lms", "Canvas LMS", "tool", "learning management system", "gradescope"),
    _s("rest-apis", "REST APIs", "tool", "rest api", "api integration", "http api"),
    _s("postgres", "PostgreSQL", "tool", "postgres", "psql"),
    _s("mongodb", "MongoDB", "tool", "nosql"),
    _s("redis", "Redis", "tool"),
    _s("wandb", "Weights & Biases", "tool", "wandb", "weights and biases"),
    _s("arduino", "Arduino", "tool", "raspberry pi", "microcontroller"),
    _s("solidworks", "SolidWorks", "tool", "fusion 360", "cad modeling", "cad modelling"),
    _s("qualtrics", "Qualtrics", "tool", "survey platform", "redcap"),
    _s("spss", "SPSS", "tool", "stata"),
    _s(
        "adobe-creative",
        "Adobe Creative Suite",
        "tool",
        "photoshop",
        "illustrator",
        "premiere pro",
        "indesign",
    ),
    _s(
        "av-equipment",
        "AV Equipment",
        "tool",
        "av equipment",
        "audio visual",
        "audio-visual",
        "projectors",
        "sound board",
        "livestream setup",
    ),
    _s(
        "pos-systems",
        "Point-of-Sale Systems",
        "tool",
        "point of sale",
        "pos system",
        "cash register",
    ),
    _s(
        "ticketing-systems",
        "Ticketing Systems",
        "tool",
        "servicenow",
        "zendesk",
        "help desk ticketing",
        "jira service desk",
    ),
    # ------------------------------------------------------------ domains
    _s("machine-learning", "Machine Learning", "domain", "ml", "statistical learning"),
    _s("deep-learning", "Deep Learning", "domain", "neural networks", "neural network"),
    _s(
        "computer-vision",
        "Computer Vision",
        "domain",
        "image recognition",
        "visual recognition",
        "object detection",
        "image segmentation",
    ),
    _s(
        "nlp",
        "Natural Language Processing",
        "domain",
        "nlp",
        "computational linguistics",
        "text mining",
    ),
    _s(
        "llm",
        "Large Language Models",
        "domain",
        "llm",
        "llms",
        "large language model",
        "foundation model",
        "foundation models",
    ),
    _s(
        "rag",
        "Retrieval-Augmented Generation",
        "method",
        "rag",
        "retrieval augmented generation",
        "retrieval-augmented",
    ),
    _s(
        "fine-tuning",
        "Fine-tuning",
        "method",
        "finetuning",
        "fine tuning",
        "instruction tuning",
        "lora",
        "peft",
    ),
    _s(
        "prompt-engineering",
        "Prompt Engineering",
        "method",
        "prompting",
        "prompt design",
        "in-context learning",
    ),
    _s(
        "reinforcement-learning",
        "Reinforcement Learning",
        "domain",
        "rl",
        "deep rl",
        "rlhf",
        "policy gradient",
    ),
    _s(
        "robotics",
        "Robotics",
        "domain",
        "robot",
        "robots",
        "robotic manipulation",
        "humanoid",
        "humanoids",
    ),
    _s(
        "robot-learning",
        "Robot Learning",
        "domain",
        "imitation learning",
        "learning from demonstration",
        "visuomotor policy",
        "teleoperation",
    ),
    _s(
        "hci",
        "Human-Computer Interaction",
        "domain",
        "hci",
        "human computer interaction",
        "human-centered design",
    ),
    _s(
        "user-research",
        "User Research",
        "method",
        "usability testing",
        "user interviews",
        "user studies",
        "contextual inquiry",
    ),
    _s(
        "ux-design",
        "UX Design",
        "domain",
        "user experience design",
        "interaction design",
        "ui design",
        "wireframing",
    ),
    _s(
        "data-analysis",
        "Data Analysis",
        "domain",
        "data analytics",
        "exploratory data analysis",
        "data wrangling",
        "analyzing data",
    ),
    _s(
        "data-visualization",
        "Data Visualisation",
        "method",
        "data visualization",
        "dataviz",
        "matplotlib",
        "d3.js",
    ),
    _s(
        "statistics",
        "Statistics",
        "domain",
        "statistical analysis",
        "hypothesis testing",
        "regression analysis",
        "bayesian statistics",
    ),
    _s("linear-algebra", "Linear Algebra", "domain", "matrix algebra", "matrix computations"),
    _s("probability", "Probability", "domain", "probability theory", "stochastic processes"),
    _s(
        "optimization",
        "Optimization",
        "method",
        "optimisation",
        "convex optimization",
        "numerical optimization",
    ),
    _s(
        "algorithms",
        "Algorithms & Data Structures",
        "domain",
        "data structures",
        "algorithm design",
        "algorithms",
    ),
    _s(
        "systems-programming",
        "Systems Programming",
        "domain",
        "operating systems",
        "distributed systems",
        "concurrency",
    ),
    _s(
        "databases",
        "Databases",
        "domain",
        "database design",
        "relational databases",
        "data modeling",
    ),
    _s(
        "web-development",
        "Web Development",
        "domain",
        "full-stack",
        "frontend development",
        "backend development",
        "web application",
    ),
    _s(
        "mobile-development",
        "Mobile Development",
        "domain",
        "ios development",
        "android development",
        "react native",
    ),
    _s("embedded-systems", "Embedded Systems", "domain", "firmware", "embedded c"),
    _s("signal-processing", "Signal Processing", "domain", "dsp", "fourier analysis"),
    _s(
        "speech-audio",
        "Speech & Audio",
        "domain",
        "speech recognition",
        "text-to-speech",
        "audio processing",
        "asr",
    ),
    _s(
        "graphics",
        "Computer Graphics",
        "domain",
        "rendering",
        "ray tracing",
        "3d graphics",
        "geometry processing",
    ),
    _s(
        "simulation",
        "Simulation",
        "method",
        "physics simulation",
        "numerical simulation",
        "monte carlo",
    ),
    _s(
        "bioinformatics",
        "Bioinformatics",
        "domain",
        "computational biology",
        "genomics",
        "sequencing data",
    ),
    _s("neuroscience", "Neuroscience", "domain", "cognitive neuroscience", "fmri", "eeg", "mri"),
    _s(
        "behavioral-experiments",
        "Behavioural Experiments",
        "method",
        "behavioral experiments",
        "psychophysics",
        "online experiments",
        "experiment design",
        "running experiments",
    ),
    _s(
        "causal-inference",
        "Causal Inference",
        "method",
        "a/b testing",
        "randomized controlled trial",
        "quasi-experimental",
    ),
    _s(
        "generative-models",
        "Generative Models",
        "domain",
        "diffusion models",
        "diffusion model",
        "gans",
        "variational autoencoder",
        "generative ai",
    ),
    _s(
        "multimodal",
        "Multimodal Learning",
        "domain",
        "vision-language",
        "vision language model",
        "vlm",
        "multimodal models",
    ),
    _s(
        "ai-safety",
        "AI Safety & Alignment",
        "domain",
        "ai safety",
        "alignment research",
        "red teaming",
        "model evaluation",
    ),
    _s("accessibility", "Accessibility", "domain", "assistive technology", "wcag", "screen reader"),
    # -------------------------------------------------------------- soft
    _s(
        "teaching",
        "Teaching",
        "soft",
        "teaching assistant",
        "course assistant",
        "section leading",
        "lecturing",
        "instruction",
        "grading",
    ),
    _s("tutoring", "Tutoring", "soft", "tutor", "peer tutoring", "academic coaching"),
    _s("mentoring", "Mentoring", "soft", "mentorship", "mentoring students"),
    _s(
        "public-speaking",
        "Public Speaking",
        "soft",
        "presentations",
        "oral communication",
        "presenting",
    ),
    _s(
        "technical-writing",
        "Technical Writing",
        "soft",
        "documentation",
        "writing documentation",
        "scientific writing",
    ),
    _s(
        "research-writing",
        "Research Writing",
        "soft",
        "literature review",
        "paper writing",
        "manuscript preparation",
    ),
    _s("collaboration", "Collaboration", "soft", "teamwork", "collaborative work", "team player"),
    _s(
        "communication",
        "Communication",
        "soft",
        "communication skills",
        "interpersonal skills",
        "written communication",
    ),
    _s(
        "organization",
        "Organisation",
        "soft",
        "organizational skills",
        "organisational skills",
        "attention to detail",
        "time management",
    ),
    _s("leadership", "Leadership", "soft", "team lead", "leading a team", "project leadership"),
    _s("problem-solving", "Problem Solving", "soft", "analytical thinking", "critical thinking"),
    _s(
        "project-management",
        "Project Management",
        "soft",
        "project coordination",
        "agile",
        "scrum",
    ),
    # ------------------------------------------------------------ service
    _s(
        "customer-service",
        "Customer Service",
        "service",
        "patron services",
        "guest services",
        "front desk",
        "customer support",
        "direct interaction with patrons",
    ),
    _s("cash-handling", "Cash Handling", "service", "handling cash", "money handling", "register"),
    _s(
        "scheduling",
        "Scheduling",
        "service",
        "shift scheduling",
        "calendar management",
        "appointment scheduling",
    ),
    _s(
        "event-planning",
        "Event Planning",
        "service",
        "event coordination",
        "event management",
        "event setup",
    ),
    _s(
        "technical-support",
        "Technical Support",
        "service",
        "it support",
        "help desk",
        "helpdesk",
        "user support",
    ),
    _s(
        "hardware-troubleshooting",
        "Hardware Troubleshooting",
        "service",
        "hardware repair",
        "computer repair",
        "equipment troubleshooting",
    ),
    _s(
        "library-services",
        "Library Services",
        "service",
        "circulation desk",
        "shelving",
        "call number",
        "stacks maintenance",
    ),
    _s("food-service", "Food Service", "service", "barista", "food handling", "food prep"),
    _s(
        "childcare",
        "Childcare",
        "service",
        "working with children",
        "young children",
        "youth programs",
        "camp counselor",
    ),
    _s("lab-safety", "Lab Safety", "service", "laboratory safety", "biosafety", "safety protocols"),
    _s(
        "data-entry",
        "Data Entry",
        "service",
        "records management",
        "transcription",
        "data collection",
    ),
    _s("inventory", "Inventory Management", "service", "stock management", "inventory control"),
)

SKILL_BY_SLUG: dict[str, SkillDef] = {s.slug: s for s in SKILLS}


# ------------------------------------------------------------------ topics

_PARENT_TOPICS: tuple[TopicDef, ...] = (
    TopicDef("machine-learning-area", "Machine Learning", None, ("ml", "learning algorithms")),
    TopicDef("language-speech-area", "Language & Speech", None, ("language technology",)),
    TopicDef("vision-graphics-area", "Vision & Graphics", None, ("visual computing",)),
    TopicDef("robotics-embodied-area", "Robotics & Embodied AI", None, ("embodied intelligence",)),
    TopicDef("human-centered-area", "Human-Centered Computing", None, ("human-centered ai",)),
    TopicDef("ai-society-area", "AI & Society", None, ("responsible ai",)),
    TopicDef("systems-area", "Systems", None, ("computer systems",)),
    TopicDef("ai-science-health-area", "AI for Science & Health", None, ("ai for science",)),
)

_CHILD_TOPICS: tuple[TopicDef, ...] = (
    TopicDef(
        "llm-agents",
        "LLM Agents",
        "language-speech-area",
        ("language agents", "agentic ai", "tool use", "ai agents", "autonomous agents"),
        "Language-model agents that plan, call tools and act over long horizons.",
    ),
    TopicDef(
        "large-language-models",
        "Large Language Models",
        "language-speech-area",
        ("llm", "llms", "large language model", "foundation models", "language modeling"),
        "Pre-training, evaluation and adaptation of large language models.",
    ),
    TopicDef(
        "nlp",
        "Natural Language Processing",
        "language-speech-area",
        ("nlp", "computational linguistics", "text understanding", "question answering"),
        "Systems that read, generate and reason over human language.",
    ),
    TopicDef(
        "speech-audio",
        "Speech & Audio",
        "language-speech-area",
        ("speech recognition", "text-to-speech", "audio models", "spoken language"),
        "Spoken language and audio understanding or synthesis.",
    ),
    TopicDef(
        "multimodal-learning",
        "Multimodal Learning",
        "machine-learning-area",
        ("vision-language", "vlm", "multimodal models", "image-text"),
        "Models that join vision, language and other modalities.",
    ),
    TopicDef(
        "reinforcement-learning",
        "Reinforcement Learning",
        "machine-learning-area",
        ("rl", "deep rl", "rlhf", "policy optimization", "sequential decision making"),
        "Learning to act from reward or preference signals.",
    ),
    TopicDef(
        "generative-models",
        "Generative Models",
        "machine-learning-area",
        ("diffusion models", "gans", "flow matching", "generative modeling"),
        "Diffusion, flow and autoregressive models of complex data.",
    ),
    TopicDef(
        "ml-theory",
        "Machine Learning Theory",
        "machine-learning-area",
        ("learning theory", "generalization theory", "optimization theory"),
        "Why learning algorithms work: generalisation, optimisation, sample complexity.",
    ),
    TopicDef(
        "ml-systems",
        "ML Systems",
        "systems-area",
        ("mlsys", "efficient inference", "model serving", "distributed training", "quantization"),
        "Making training and inference fast, cheap and reliable.",
    ),
    TopicDef(
        "data-systems",
        "Data Systems",
        "systems-area",
        ("databases", "data management", "query processing", "data pipelines"),
        "Storage, query and pipeline infrastructure for data at scale.",
    ),
    TopicDef(
        "computer-vision",
        "Computer Vision",
        "vision-graphics-area",
        ("visual recognition", "object detection", "scene understanding", "3d vision"),
        "Recognising and reconstructing the visual world.",
    ),
    TopicDef(
        "graphics",
        "Computer Graphics",
        "vision-graphics-area",
        ("rendering", "geometry processing", "animation", "physical simulation"),
        "Synthesising and simulating images, geometry and motion.",
    ),
    TopicDef(
        "robotics",
        "Robotics",
        "robotics-embodied-area",
        ("robot", "manipulation", "humanoid robots", "motion planning", "control"),
        "Perception, planning and control for physical robots.",
    ),
    TopicDef(
        "robot-learning",
        "Robot Learning",
        "robotics-embodied-area",
        (
            "imitation learning",
            "learning from demonstration",
            "visuomotor policies",
            "sim-to-real",
            "teleoperation",
        ),
        "Learning robot behaviour from data, demonstration or simulation.",
    ),
    TopicDef(
        "embodied-ai",
        "Embodied AI",
        "robotics-embodied-area",
        ("embodied agents", "navigation", "household robots", "embodied reasoning"),
        "Agents that perceive and act in physical or simulated environments.",
    ),
    TopicDef(
        "human-ai-interaction",
        "Human-AI Interaction",
        "human-centered-area",
        ("human-ai collaboration", "ai assistants", "mixed-initiative", "human-in-the-loop"),
        "How people work with, trust and steer AI systems.",
    ),
    TopicDef(
        "hci",
        "Human-Computer Interaction",
        "human-centered-area",
        ("hci", "interaction design", "user experience research", "interface design"),
        "Designing and studying interactive systems.",
    ),
    TopicDef(
        "ai-for-education",
        "AI for Education",
        "human-centered-area",
        ("educational technology", "learning at scale", "intelligent tutoring", "edtech"),
        "Tutoring, feedback and learning analytics with AI.",
    ),
    TopicDef(
        "computational-cognitive-science",
        "Computational Cognitive Science",
        "human-centered-area",
        ("cognitive modeling", "theory of mind", "social learning", "cognitive science"),
        "Computational models of how people think and learn.",
    ),
    TopicDef(
        "ai-safety-alignment",
        "AI Safety & Alignment",
        "ai-society-area",
        ("alignment", "ai safety", "interpretability", "red teaming", "model evaluations"),
        "Making capable models honest, controllable and evaluable.",
    ),
    TopicDef(
        "computational-social-science",
        "Computational Social Science",
        "ai-society-area",
        ("social computing", "online communities", "computational sociology", "misinformation"),
        "Studying social behaviour with computational methods.",
    ),
    TopicDef(
        "ai-for-health",
        "AI for Health",
        "ai-science-health-area",
        ("medical imaging", "clinical machine learning", "biomedical ai", "health informatics"),
        "Clinical, biomedical and health-systems applications of AI.",
    ),
)

BUILTIN_TOPICS: tuple[TopicDef, ...] = _PARENT_TOPICS + _CHILD_TOPICS


_SLUGGY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ACRONYMS = frozenset({"ai", "ml", "nlp", "hci", "llm", "llms", "rl", "cv", "ui", "ux"})


def humanise_slug(slug: str) -> str:
    """Turn a slug into a label a person would write.

    A label identical to its slug means a slug leaked into the UI, which reads
    as developer output rather than product copy.
    """
    words = []
    for word in slug.replace("_", "-").split("-"):
        if not word:
            continue
        if word in _ACRONYMS:
            words.append(word.upper())
        elif word == "and":
            words.append("&")
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def clean_label(label: str | None, slug: str) -> str:
    if not label or (_SLUGGY.fullmatch(label) and label == slug):
        return humanise_slug(slug)
    return label


def _coerce_topic(payload: dict, parent_hint: str | None = None) -> TopicDef | None:
    slug = normalize(payload.get("slug") or payload.get("id") or "").replace(" ", "-")
    label = (payload.get("label") or payload.get("name") or "").strip()
    if not slug or not label:
        return None
    parent = payload.get("parent") or payload.get("parent_slug") or parent_hint
    aliases = payload.get("aliases") or payload.get("synonyms") or []
    return TopicDef(
        slug=slug,
        label=clean_label(label, slug),
        parent=(normalize(parent).replace(" ", "-") or None) if parent else None,
        aliases=tuple(str(a) for a in aliases if str(a).strip()),
        description=payload.get("description"),
    )


def _parse_ontology(payload: object) -> tuple[TopicDef, ...]:
    """Accept the shapes a harvested ontology file plausibly takes.

    Anything unrecognised is skipped rather than guessed at; if nothing usable
    survives, the caller falls back to the built-in ontology.
    """
    out: list[TopicDef] = []
    if isinstance(payload, dict):
        for key in ("parents", "areas"):
            for item in payload.get(key) or []:
                if isinstance(item, dict):
                    topic = _coerce_topic(item)
                    if topic:
                        out.append(TopicDef(topic.slug, topic.label, None, topic.aliases, topic.description))
        for key in ("topics", "children", "items"):
            for item in payload.get(key) or []:
                if isinstance(item, dict):
                    topic = _coerce_topic(item)
                    if topic:
                        out.append(topic)
        if not out:
            # {"parent-slug": {"label": ..., "children": [...]}}
            for slug, body in payload.items():
                if not isinstance(body, dict):
                    continue
                parent = _coerce_topic({"slug": slug, **body})
                if parent is None:
                    continue
                out.append(TopicDef(parent.slug, parent.label, None, parent.aliases, parent.description))
                for child in body.get("children") or []:
                    if isinstance(child, dict):
                        topic = _coerce_topic(child, parent_hint=parent.slug)
                        if topic:
                            out.append(topic)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                topic = _coerce_topic(item)
                if topic:
                    out.append(topic)
    # Parents first so ensure_topics can resolve parent ids in one pass.
    seen: set[str] = set()
    ordered = [t for t in out if t.parent is None] + [t for t in out if t.parent is not None]
    unique: list[TopicDef] = []
    for topic in ordered:
        if topic.slug in seen:
            continue
        seen.add(topic.slug)
        unique.append(topic)
    return tuple(unique)


@lru_cache(maxsize=1)
def load_topic_ontology(path: Path | None = None) -> tuple[TopicDef, ...]:
    """The research-topic ontology, from the harvest file when it exists."""
    source = path or TOPIC_ONTOLOGY_PATH
    if source.exists():
        try:
            parsed = _parse_ontology(json.loads(source.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            parsed = ()
        if parsed:
            return parsed
    return BUILTIN_TOPICS


def reset_ontology_cache() -> None:
    load_topic_ontology.cache_clear()
    topic_index.cache_clear()


@lru_cache(maxsize=1)
def topic_index() -> dict[str, TopicDef]:
    return {t.slug: t for t in load_topic_ontology()}


def topic_label(slug: str) -> str:
    topic = topic_index().get(slug)
    return topic.label if topic else slug.replace("-", " ").title()


def skill_label(slug: str) -> str:
    skill = SKILL_BY_SLUG.get(slug)
    return skill.label if skill else slug.replace("-", " ").title()


def skill_labels(slugs: object) -> list[str]:
    if not slugs:
        return []
    return [skill_label(str(s)) for s in slugs]  # type: ignore[union-attr]


# ----------------------------------------------------------------- matching


# Characters that look like a word boundary but almost always mean the token is
# part of a name rather than a standalone mention: "R&DE", "C++Builder", "C#".
_GLUE_CHARS = "&+#/-_."


def _term_hit(text: str, term: str, veto: tuple[str, ...]) -> tuple[int, int] | None:
    """Find ``term`` in ``text`` with the short-alias rules applied."""
    if len(term) <= 2:
        span = find_phrase(text, term.upper(), case_sensitive=True)
    else:
        span = find_phrase(text, term)
    if span is None:
        return None

    # A one-letter language name is the highest-risk match in the whole
    # vocabulary: "R" appears inside "R&DE", "R&D", "Q&R". Word boundaries alone
    # are not enough, because & is a boundary. Putting a skill the student does
    # not have on their profile is exactly the fabrication this product forbids,
    # so single letters must not be glued to a neighbouring token.
    if len(term) == 1:
        before = text[span[0] - 1] if span[0] > 0 else " "
        after = text[span[1]] if span[1] < len(text) else " "
        if before in _GLUE_CHARS or after in _GLUE_CHARS:
            return None

    if veto:
        window = text[max(0, span[0] - 24) : span[1] + 24]
        if any(find_phrase(window, phrase) for phrase in veto):
            return None
    return span


def match_skills(text: str | None) -> list[tuple[str, str]]:
    """Canonical skills mentioned in ``text``, each with a quotable snippet.

    Word-boundary safe by construction: ``r`` does not match inside ``react``
    and ``ai`` does not match inside ``chair``.
    """
    if not text:
        return []
    haystack = str(text)
    found: list[tuple[str, str]] = []
    for skill in SKILLS:
        for term in skill.terms:
            span = _term_hit(haystack, term, skill.veto)
            if span is not None:
                found.append((skill.slug, phrase_snippet(haystack, span)))
                break
    return found


def match_skill_slugs(text: str | None) -> set[str]:
    return {slug for slug, _ in match_skills(text)}


def resolve_skill(value: str | None) -> str | None:
    """Map a free-form skill string onto a canonical slug, or ``None``.

    Returning ``None`` is the honest answer for something outside the
    vocabulary — callers keep the raw string rather than inventing a slug.
    """
    if not value:
        return None
    raw = str(value).strip()
    if raw in SKILL_BY_SLUG:
        return raw
    lowered = normalize(raw)
    if lowered in SKILL_BY_SLUG:
        return lowered
    for skill in SKILLS:
        if lowered == normalize(skill.label):
            return skill.slug
        if any(lowered == normalize(alias) for alias in skill.aliases):
            return skill.slug
    hits = match_skills(raw)
    if len(hits) == 1:
        return hits[0][0]
    best_slug, best_score = None, 0.0
    for skill in SKILLS:
        score = fuzzy_ratio(lowered, skill.label)
        if score > best_score:
            best_slug, best_score = skill.slug, score
    return best_slug if best_score >= 0.93 else None


def resolve_skills(values: object) -> list[str]:
    out: list[str] = []
    for value in values or []:  # type: ignore[union-attr]
        slug = resolve_skill(str(value))
        if slug and slug not in out:
            out.append(slug)
    return out


def match_topics(text: str | None) -> list[tuple[str, float]]:
    """Research topics mentioned in ``text`` with a 0..1 confidence weight.

    Weight rises with the number of distinct vocabulary terms seen, and
    parent-level ("Machine Learning") matches are discounted because they say
    much less about what a lab actually does than a leaf topic does.
    """
    if not text:
        return []
    haystack = str(text)
    parents = {t.slug for t in load_topic_ontology() if t.parent is None}
    scored: list[tuple[str, float]] = []
    for topic in load_topic_ontology():
        terms = (topic.label, *topic.aliases)
        hits = sum(1 for term in terms if _term_hit(haystack, term, ()) is not None)
        if not hits:
            continue
        weight = min(1.0, 0.6 + 0.15 * (hits - 1))
        if topic.slug in parents:
            weight *= 0.6
        scored.append((topic.slug, round(weight, 3)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


_TOPIC_ALIAS_EXTRA: dict[str, str] = {
    "multimodal ai": "multimodal-learning",
    "multimodal": "multimodal-learning",
    "ai agents": "llm-agents",
    "ai agent": "llm-agents",
    "agents": "llm-agents",
    "agent": "llm-agents",
    "agentic": "llm-agents",
    "agentic ai": "llm-agents",
    "autonomous agents": "llm-agents",
    "language agents": "llm-agents",
    "llm agents": "llm-agents",
    "llms": "large-language-models",
    "llm": "large-language-models",
    "foundation models": "large-language-models",
    "human ai interaction": "human-ai-interaction",
    "human-computer interaction": "hci",
    "ai + education": "ai-for-education",
    "ai and education": "ai-for-education",
    "ai education": "ai-for-education",
    "ai for education": "ai-for-education",
    "ai in education": "ai-for-education",
    "education": "ai-for-education",
    "education technology": "ai-for-education",
    "educational technology": "ai-for-education",
    "edtech": "ai-for-education",
    "computational education": "ai-for-education",
    "cs education": "ai-for-education",
    "computer science education": "ai-for-education",
    "computing education": "ai-for-education",
    "ml systems": "ml-systems",
    "rl": "reinforcement-learning",
    "cv": "computer-vision",
    "nlp": "nlp",
    "natural language processing": "nlp",
    "computational linguistics": "nlp",
    "alignment": "ai-safety-alignment",
    "ai safety": "ai-safety-alignment",
}


# Words that describe the SHAPE of the work rather than its subject. "part-time"
# is not a research topic and must never be resolved as one: a student who types
# it wants a job with few hours, and answering with a robotics lab would be a
# wrong answer dressed up as a clever one. Kept deliberately narrow — only
# employment-shape phrasing lives here, because a broad word like "research" or
# "lab" reads as a subject at least as often as a category ("Research Assistant,
# Culture and Emotion Lab" is an on-campus job).
_KIND_ALIAS_EXTRA: dict[str, tuple[str, ...]] = {
    "part-time": ("part_time", "on_campus"),
    "part time": ("part_time", "on_campus"),
    "parttime": ("part_time", "on_campus"),
    "on-campus": ("on_campus", "part_time"),
    "on campus": ("on_campus", "part_time"),
    "campus job": ("on_campus", "part_time"),
    "campus jobs": ("on_campus", "part_time"),
    "student job": ("on_campus", "part_time"),
    "student jobs": ("on_campus", "part_time"),
    "job": ("on_campus", "part_time"),
    "jobs": ("on_campus", "part_time"),
    "hourly": ("on_campus", "part_time"),
    "work-study": ("on_campus", "part_time"),
    "work study": ("on_campus", "part_time"),
}

#: Human wording for a resolved kind, so the UI can say what it narrowed to.
KIND_LABEL: dict[str, str] = {
    "on_campus": "On-campus",
    "part_time": "Part-time",
    "research_opening": "Research opening",
    "research_outreach": "Research outreach",
}


def resolve_kinds(value: str | None) -> tuple[str, ...]:
    """Opportunity types a query asks for, or ``()`` when it asks for none.

    Matching is phrase-based rather than substring-based so "part-time research
    assistant" narrows to jobs while "apartment" never does.
    """
    if not value:
        return ()
    text = str(value)
    out: list[str] = []
    for alias, kinds in _KIND_ALIAS_EXTRA.items():
        if find_phrase(text, alias) is None:
            continue
        for kind in kinds:
            if kind not in out:
                out.append(kind)
    return tuple(out)


def resolve_topic(value: str | None) -> str | None:
    if value:
        direct = _TOPIC_ALIAS_EXTRA.get(" ".join(value.lower().split()))
        if direct:
            return direct
        # A query that is nothing but a shape word has already been answered by
        # resolve_kinds(); guessing a topic for it as well would bury the honest
        # answer under a lab that has nothing to do with hours.
        if normalize(value) in _KIND_ALIAS_EXTRA:
            return None
    if not value:
        return None
    raw = str(value).strip()
    index = topic_index()
    if raw in index:
        return raw
    lowered = normalize(raw)
    slugified = lowered.replace(" ", "-")
    if slugified in index:
        return slugified
    for topic in load_topic_ontology():
        if lowered == normalize(topic.label) or any(
            lowered == normalize(alias) for alias in topic.aliases
        ):
            return topic.slug
    hits = match_topics(raw)
    return hits[0][0] if hits else None


# ------------------------------------------------------------------ seeding


@dataclass(slots=True)
class SeedResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    slugs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int]:
        return {"created": self.created, "updated": self.updated, "unchanged": self.unchanged}


def ensure_skills(db: Session) -> SeedResult:
    """Upsert the canonical skill vocabulary. Safe to call on every startup."""
    existing = {row.slug: row for row in db.execute(select(Skill)).scalars()}
    result = SeedResult()
    for skill in SKILLS:
        aliases = list(skill.aliases)
        row = existing.get(skill.slug)
        if row is None:
            db.add(Skill(slug=skill.slug, label=skill.label, category=skill.category, aliases=aliases))
            result.created += 1
            result.slugs.append(skill.slug)
            continue
        if (row.label, row.category, list(row.aliases or [])) != (skill.label, skill.category, aliases):
            row.label = skill.label
            row.category = skill.category
            row.aliases = aliases
            result.updated += 1
        else:
            result.unchanged += 1
    db.flush()
    return result


def ensure_topics(db: Session) -> SeedResult:
    """Upsert the research-topic ontology (parents first, then children)."""
    ontology = load_topic_ontology()
    existing = {row.slug: row for row in db.execute(select(ResearchTopic)).scalars()}
    result = SeedResult()

    def upsert(topic: TopicDef, parent_id: object | None) -> ResearchTopic:
        row = existing.get(topic.slug)
        aliases = list(topic.aliases)
        if row is None:
            row = ResearchTopic(
                slug=topic.slug,
                label=topic.label,
                aliases=aliases,
                description=topic.description,
                parent_id=parent_id,
            )
            db.add(row)
            existing[topic.slug] = row
            result.created += 1
            result.slugs.append(topic.slug)
            return row
        current = (row.label, list(row.aliases or []), row.description, row.parent_id)
        if current != (topic.label, aliases, topic.description, parent_id):
            row.label = topic.label
            row.aliases = aliases
            row.description = topic.description
            row.parent_id = parent_id
            result.updated += 1
        else:
            result.unchanged += 1
        return row

    for topic in ontology:
        if topic.parent is None:
            upsert(topic, None)
    db.flush()
    for topic in ontology:
        if topic.parent is None:
            continue
        parent_row = existing.get(topic.parent)
        upsert(topic, parent_row.id if parent_row is not None else None)
    db.flush()
    return result


def ensure_vocabulary(db: Session) -> dict[str, dict[str, int]]:
    return {"skills": ensure_skills(db).as_dict(), "topics": ensure_topics(db).as_dict()}


# ---------------------------------------------------------------------------
# Related topics
# ---------------------------------------------------------------------------
#
# Two vocabularies meet in this product and they do not share slugs: the
# canonical ontology (llm-agents, hci, ...) and Stanford's own department area
# names harvested from the faculty directory (artificial-intelligence,
# human-centered-and-creative-ai, ...). A student who writes "LLM agents" would
# otherwise never match a lab tagged only "large-language-models", and the UI
# would say "no overlap" about a lab that obviously overlaps.
#
# This is a deliberately small, hand-checked adjacency list rather than an
# embedding: it is auditable, and a wrong edge here shows up as a wrong claim
# on a lab card.

_RELATED_PAIRS: tuple[tuple[str, str], ...] = (
    ("llm-agents", "large-language-models"),
    ("llm-agents", "artificial-intelligence"),
    ("large-language-models", "nlp"),
    ("large-language-models", "natural-language-processing-and-speech"),
    ("nlp", "natural-language-processing-and-speech"),
    ("nlp", "speech-audio"),
    ("human-ai-interaction", "hci"),
    ("human-ai-interaction", "human-centered-and-creative-ai"),
    ("hci", "human-centered-and-creative-ai"),
    ("ai-for-education", "computational-education"),
    ("ai-for-education", "computer-science-education"),
    ("llm-agents", "embodied-ai"),
    ("multimodal-learning", "computer-vision"),
    ("multimodal-learning", "large-language-models"),
    ("computer-vision", "vision-graphics-area"),
    ("robot-learning", "robotics"),
    ("robot-learning", "embodied-ai"),
    ("embodied-ai", "robotics"),
    ("reinforcement-learning", "machine-learning-area"),
    ("reinforcement-learning", "empirical-machine-learning"),
    ("ai-safety-alignment", "artificial-intelligence"),
    ("generative-models", "large-language-models"),
    ("computational-social-science", "ai-society-area"),
    ("ai-for-health", "ai-science-health-area"),
    ("ml-systems", "systems-area"),
    ("computational-cognitive-science", "cognitive-and-neuro-ai"),
)

_RELATED: dict[str, set[str]] = {}
for _a, _b in _RELATED_PAIRS:
    _RELATED.setdefault(_a, set()).add(_b)
    _RELATED.setdefault(_b, set()).add(_a)


def related_slugs(slug: str | None) -> set[str]:
    """The slug plus its hand-checked neighbours. One hop only, on purpose:
    transitive closure would connect nearly everything to everything."""
    if not slug:
        return set()
    return {slug} | _RELATED.get(slug, set())


# Department-level areas that almost every lab in the school carries. True of
# the lab, but useless as an explanation to a student — "Artificial
# Intelligence" is the answer for everybody — so callers fall back to these only
# when nothing more specific matched, and never report one as a gap.
GENERIC_TOPICS: frozenset[str] = frozenset(
    {
        "artificial-intelligence",
        "machine-learning",
        "machine-learning-area",
        "empirical-machine-learning",
        "human-centered-and-creative-ai",
        "ai-society-area",
        "human-centered-area",
        "systems-area",
        "vision-graphics-area",
        "language-speech-area",
        "robotics-embodied-area",
        "ai-science-health-area",
    }
)


def topics_related(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return b in related_slugs(a)
