"""Curated summary of the Siemens Digital Industries Software (DISW) portfolio.

Curated once from public sources (2026-07-20) instead of scraped live:
reliable, token-cheap, and still "public sources only". Trade-off: can go
stale — refresh by revisiting SOURCES.
"""

SOURCES = [
    "https://www.siemens.com/en-us/products/designcenter/cad-software/",
    "https://en.wikipedia.org/wiki/Siemens_Digital_Industries_Software",
    "https://www.siemens.com/en-us/",
    "https://www.siemens.com/en-us/partners/software/join-partner-program/build/technology-partners/",
    "https://news.siemens.com/en-us/siemens-xcelerator-open-business-platform-launch/",
]

SIEMENS_DISW_CONTEXT = """Siemens Digital Industries Software (DISW) sells industrial software under the
Siemens Xcelerator platform, covering the full product and production lifecycle:

- Designcenter / NX: CAD/CAM/CAE suite for product engineering (mechanical and
  electrical design, machining, AI-assisted design).
- Solid Edge: mainstream 3D CAD for mid-market manufacturers.
- Teamcenter: product lifecycle management (PLM) — product data, BOM, and
  collaboration across engineering and manufacturing.
- Simcenter: simulation and physical testing (multiphysics, CFD such as
  STAR-CCM+, system simulation such as Amesim); complemented by the 2025
  Altair acquisition (simulation, HPC, data analytics and AI).
- Opcenter: manufacturing operations management — MES, advanced planning and
  scheduling, quality management.
- Tecnomatix: digital manufacturing — factory planning, plant simulation,
  robotics programming.
- Insights Hub: industrial IoT platform — connects machines and factory data
  to analytics and dashboards.
- Mendix: low-code platform for building enterprise and industrial apps.
- Polarion: application lifecycle management (ALM) — requirements and software
  engineering processes.
- Capital: electrical/electronic (E/E) systems and wire-harness engineering.
- Siemens EDA (Calibre, Questa, Tessent, PCB tools): electronic design
  automation for chip and board design.

DISW partners with technology companies whose products complement this
portfolio — typically companies adding AI, data, robotics, sensing or vertical
capabilities that integrate with the products above, rather than competing
head-on with them."""


# Publicly named partners of the Siemens Xcelerator ecosystem. Siemens reports
# 700+ certified partners; this is a representative sample of the ones named in
# public announcements, not an exhaustive list.
SIEMENS_PARTNERS = """Publicly named partners in the Siemens Xcelerator ecosystem, with the role
each plays:

- NVIDIA — accelerated computing and AI/graphics. Partnership covers the
  industrial metaverse and AI-driven digital twins; extends Simcenter and
  Tecnomatix with simulation and visualization compute.
- Microsoft — cloud (Azure) and productivity. Hosts and integrates Xcelerator
  services; connects PLM data to enterprise collaboration tools.
- Amazon Web Services (AWS) — cloud infrastructure hosting Siemens Xcelerator
  SaaS offerings such as Teamcenter X and Simcenter cloud services.
- SAP — enterprise resource planning. Connects Teamcenter PLM data with ERP
  processes (BOM, procurement, production orders).
- Bentley Systems — infrastructure and plant engineering software. Complements
  the DISW product-engineering portfolio in the built-environment domain.
- Accenture — global systems integrator. Deploys and integrates Siemens
  industrial software at manufacturing customers.
- Atos — IT services and digital transformation; integration and managed
  services around the Xcelerator portfolio.
- Deloitte — consulting and systems integration for digital manufacturing
  transformation programs.

The partner program is organised into three categories: Build & Sell (partners
who develop software or hardware extending Xcelerator), Consult & Service
(integrators and consultancies), and Enable & Run (operations and hosting).
Technology partners are specifically companies that "build innovative software
and hardware solutions that enhance or extend the Siemens Xcelerator portfolio",
often industry-specific or use-case specific, leveraging the open architecture
of Siemens products."""
