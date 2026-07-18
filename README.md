<div align="center">

<!-- Premium Visual Production Banner -->
<img src="banner.png" alt="CineNova Banner" width="100%">

# 🎬 CineNova Movie Bot

### *An Advanced, Async Anti-Flood Telegram Movie Delivery Engine*

[![Aiogram 3.x](https://img.shields.io/badge/Framework-Aiogram_3.x-blue?style=for-the-badge&logo=telegram)](https://aiogram.dev/)
[![SQLAlchemy 2.0](https://img.shields.io/badge/Database-SQLAlchemy_2.0-red?style=for-the-badge&logo=sqlite)](https://www.sqlalchemy.org/)
[![Redis Cached](https://img.shields.io/badge/Cache-Redis_Client-darkred?style=for-the-badge&logo=redis)](https://redis.io/)
[![License MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](https://opensource.org/licenses/MIT)
[![Live Demo](https://img.shields.io/badge/Live_Demo-Open_Bot-26A5E4?style=for-the-badge&logo=telegram)](https://t.me/TheCineNovaBot)

</div>

---

## 🚀 Overview

**CineNova Bot** is a high-performance, asynchronous Telegram bot architecture built with **Aiogram 3**, **SQLAlchemy 2.0**, and **Redis**. It is specifically engineered to dynamically index, search, and securely deliver movie files with automated self-destruction mechanisms to comply with copyright metadata regulations.

> ⚡ **Core Philosophy:** High speed, absolute privacy, strict anti-flood thresholds, and zero maintenance overhead.

---

## 🛠 System Architecture Flow

```text
User ──> Throttling Middleware ──> Force Join Check ──> Redis Cache Lookups
                                                             │
   ┌─────────────────────────────────────────────────────────┘
   ▼
[Cache Hit] ──> Deliver Asset File Instantly
   │
   ▼ [Cache Miss]
Database Engine ──> Full-Text Search Match ──> Sync Cache ──> Async Delete Task Launched