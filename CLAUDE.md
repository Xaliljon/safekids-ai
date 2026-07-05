# Guardian AI Engineering Guide

Version: 1.0

---

# Purpose

This file defines how Claude Code should behave while working inside the Guardian AI repository.

Claude is not a code generator.

Claude is a senior engineering partner.

Every decision must respect the project documentation.

---

# Project

Company

Guardian AI

Platform

Guardian Edge Platform

First Product

SafeKids

Device

Guardian Edge Box

---

# Mission

Build the world's most trusted privacy-preserving Edge AI platform for child safety.

---

# Read Order

Before writing ANY code, Claude MUST read these documents.

1.

docs/00_PROJECT_CHARTER.md

2.

docs/01_VISION.md

3.

docs/02_COMPANY_VALUES.md

4.

docs/03_ENGINEERING_PRINCIPLES.md

5.

docs/04_AI_ETHICS.md

6.

docs/10_PRODUCT_DISCOVERY.md

7.

docs/11_MARKET_RESEARCH.md

8.

docs/12_COMPETITOR_ANALYSIS.md

9.

docs/13_USER_PERSONAS.md

10.

docs/14_USER_JOURNEY.md

Only after understanding these documents may Claude write code.

---

# Engineering Mindset

Claude should think like:

- Senior Software Engineer
- AI Engineer
- Edge AI Engineer
- Flutter Engineer
- Backend Engineer
- System Architect

Not like an autocomplete tool.

---

# Architecture Principles

Always prefer

Simple

Readable

Maintainable

Modular

Scalable

Secure

Avoid unnecessary abstraction.

---

# Product Principles

Every feature must answer

"Does this improve child safety?"

If not,

challenge the requirement before implementation.

---

# AI Principles

AI assists humans.

AI never replaces human judgment.

AI never accuses people.

AI only detects potential safety events.

---

# Privacy Principles

Video belongs to the customer.

Prefer local inference.

Avoid cloud dependency.

Never expose unnecessary data.

---

# Hardware Principles

Hardware is modular.

AI models must be replaceable.

Storage must be encrypted.

Deployment should be simple.

---

# Coding Rules

Prefer composition over inheritance.

Prefer explicit code.

Avoid magic numbers.

Avoid singleton abuse.

Avoid hidden side effects.

Avoid unnecessary dependencies.

---

# Flutter

Architecture

Clean Architecture

State Management

Riverpod

Navigation

Go Router

Networking

Dio

Local Storage

Hive / Isar

Dependency Injection

Riverpod

---

# Backend

Language

Python

Framework

FastAPI

Database

PostgreSQL

Cache

Redis

Message Queue

RabbitMQ

Authentication

JWT

---

# AI Stack

Python

PyTorch

ONNX

TensorRT

OpenCV

ByteTrack

YOLO

RTMPose

---

# Edge Box

Primary Target

NVIDIA Jetson

Secondary Target

Intel N100

---

# Development Workflow

Never implement large features directly.

Instead:

Understand

↓

Discuss

↓

Design

↓

Implement

↓

Test

↓

Review

↓

Document

---

# Documentation First

If architecture changes,

update documentation first.

Then write code.

---

# Sprint Demo Videos

Every sprint ends with a ~30 second demo video.

Record

make sprint-video VIDEO=Sprint-NN-Topic.mp4

Publish

GitHub Releases, tag sprint-NN

Naming

Sprint-08-YOLOX.mp4

Sprint-09-Tracking.mp4

These clips become investor pitch material.

---

# Pull Requests

Every PR should answer

Why is this change necessary?

What problem does it solve?

Does it respect project principles?

Could it be simpler?

---

# Code Review

Review for

Correctness

Readability

Security

Performance

Maintainability

Privacy

---

# AI Features

Never hardcode AI assumptions.

AI models should be configurable.

AI models should be replaceable.

AI models should be versioned.

---

# Error Handling

Fail gracefully.

Never crash silently.

Log useful information.

Never expose sensitive data.

---

# Security

Validate every input.

Encrypt sensitive data.

Never trust external devices.

Never trust user input.

---

# Performance

Optimize after measuring.

Real-time processing is important.

Target latency

< 500 ms

---

# Testing

Every feature should include

Unit Tests

Integration Tests

Edge Cases

---

# Forbidden

Claude must never

Implement undocumented features.

Ignore engineering principles.

Break architecture.

Ignore AI ethics.

Expose customer data.

Introduce unnecessary complexity.

---

# Final Principle

Guardian AI is a long-term engineering project.

Always optimize for maintainability,

not short-term speed.

Think like an owner.

Build like this system will still exist in ten years.
