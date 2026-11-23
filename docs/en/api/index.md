---
title: API Overview
description: Map of PyTestLab's public Python API, from instrument drivers to measurements and configuration.
---

<div class="api-overview" markdown="1">

# PyTestLab API

<p class="api-lead">A task-oriented map of the public API. Start with the workflow you are trying to build, then use the reference pages for exact signatures and behavior.</p>

<div class="api-callout">
<strong>New to PyTestLab?</strong>
<span>Follow the <a href="../user_guide/getting_started/">Getting Started guide</a> first. Return here when you need a class, subsystem, or configuration model by name.</span>
</div>

## Start with a task

<div class="api-card-grid">
<a class="api-card" href="instruments/">
<span class="api-card-index">01 · Connect</span>
<strong class="api-card-title">Instrument drivers</strong>
<span class="api-card-description">Select a profile-backed driver for oscilloscopes, power supplies, meters, loads, and analyzers.</span>
<span class="api-card-link">Browse instruments →</span>
</a>
<a class="api-card" href="measurements/">
<span class="api-card-index">02 · Acquire</span>
<strong class="api-card-title">Measurement sessions</strong>
<span class="api-card-description">Define parameters, register acquisition functions, run sweeps, and inspect structured results.</span>
<span class="api-card-link">Build a measurement →</span>
</a>
<a class="api-card" href="experiments/">
<span class="api-card-index">03 · Preserve</span>
<strong class="api-card-title">Experiments &amp; results</strong>
<span class="api-card-description">Organize trials, plot data, save artifacts, and retrieve results from the database layer.</span>
<span class="api-card-link">Work with results →</span>
</a>
<a class="api-card" href="config/">
<span class="api-card-index">04 · Configure</span>
<strong class="api-card-title">Profiles &amp; configuration</strong>
<span class="api-card-description">Understand validated instrument, bench, runtime, and simulation configuration models.</span>
<span class="api-card-link">Configure a bench →</span>
</a>
</div>

## Browse by subsystem

<table class="api-reference-table">
<thead>
<tr><th>Subsystem</th><th>Primary entry point</th><th>Use it for</th></tr>
</thead>
<tbody>
<tr><td><a href="instruments/">Instruments</a></td><td><code>AutoInstrument</code></td><td>Drivers, profiles, identity, lifecycle, and instrument-specific operations.</td></tr>
<tr><td><a href="measurements/">Measurements</a></td><td><code>MeasurementSession</code></td><td>Repeatable parameter sweeps and acquisition functions.</td></tr>
<tr><td><a href="experiments/">Experiments</a></td><td><code>Experiment</code></td><td>Trials, plots, Parquet export, and database persistence.</td></tr>
<tr><td><a href="backends/">Backends</a></td><td>Simulation / replay</td><td>Choose real, simulated, replay, or circuit-simulation communication.</td></tr>
<tr><td><a href="config/">Configuration</a></td><td>Config models</td><td>Validate instrument, bench, and runtime settings.</td></tr>
<tr><td><a href="errors/">Errors</a> &amp; <a href="common/">utilities</a></td><td>Shared types</td><td>Diagnose failures and work with health, enums, and common helpers.</td></tr>
</tbody>
</table>

## Common paths

<ol class="api-path-list">
<li><span class="api-path-number">01</span><span><strong>Create an instrument</strong><br/><a href="instruments/autoinstrument/"><code>AutoInstrument</code></a> selects a driver from a profile.</span></li>
<li><span class="api-path-number">02</span><span><strong>Run a sweep</strong><br/><a href="measurements/"><code>MeasurementSession</code></a> owns parameters, acquisition, and cleanup.</span></li>
<li><span class="api-path-number">03</span><span><strong>Diagnose a failure</strong><br/>Start with <a href="../user_guide/troubleshooting/">Troubleshooting</a>, then consult <a href="errors/">Errors</a>.</span></li>
</ol>

<p class="api-footnote">Reference pages expose the public classes and callables in source order. Use the page outline to jump between classes, attributes, and functions.</p>

</div>
