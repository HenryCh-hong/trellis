import assert from "node:assert/strict";
import { test } from "node:test";
import { JSDOM } from "jsdom";

import { extractJob, extractList, jobIdFromUrl, readLabelled } from "../extract.js";
import { JSONLD_JOB, KNOCKOUT_JOB, LIST_PAGE, SPARSE_JOB } from "./fixtures.js";

const doc = (html) => new JSDOM(html).window.document;

test("reads a legacy knockout job page", () => {
  const job = extractJob(doc(KNOCKOUT_JOB), "https://stanford.joinhandshake.com/jobs/8000000");
  assert.equal(job.title, "Residential SOAR Specialist");
  assert.equal(job.employer, "Trilogy, Inc.");
  assert.equal(job.location, "6701 South Elizabeth Street, Chicago, Illinois 60636, United States");
  assert.equal(job.job_type, "Full-Time");
  assert.equal(job.external_key, "8000000");
  assert.equal(job.application_method, "external");
});

test("pay buried in employer prose is NOT reported as a labelled pay field", () => {
  // The rate "$22.83 /Hr." only exists inside the description on this fixture.
  // Reporting it as the job's pay would assert something the page never labelled.
  const job = extractJob(doc(KNOCKOUT_JOB), "https://stanford.joinhandshake.com/jobs/8000000");
  assert.equal(job.pay, null);
  assert.match(job.description, /22\.83/);
});

test("prefers JSON-LD when present, including the apply-by date", () => {
  const job = extractJob(doc(JSONLD_JOB), "https://stanford.joinhandshake.com/jobs/42");
  assert.equal(job.title, "Undergraduate Research Assistant");
  assert.equal(job.employer, "Stanford University");
  assert.equal(job.location, "Stanford");
  assert.equal(job.posted_at, "2026-08-01");
  assert.equal(job.apply_by, "2026-09-15");
  assert.equal(job.application_method, "handshake_quick_apply");
});

test("a sparse page yields nulls, never guesses", () => {
  const job = extractJob(doc(SPARSE_JOB), "https://stanford.joinhandshake.com/jobs/7");
  assert.equal(job.title, "Library Shelving Assistant");
  for (const key of ["employer", "location", "job_type", "pay", "posted_at", "apply_by"]) {
    assert.equal(job[key], null, `${key} should be null, got ${job[key]}`);
  }
});

test("list extraction dedupes by job id and drops untitled rows", () => {
  const jobs = extractList(doc(LIST_PAGE), "https://stanford.joinhandshake.com/stu/jobs");
  assert.equal(jobs.length, 2);
  assert.deepEqual(
    jobs.map((j) => j.external_key),
    ["111", "222"],
  );
  assert.equal(jobs[0].url, "https://stanford.joinhandshake.com/jobs/111");
});

test("job id parsing", () => {
  assert.equal(jobIdFromUrl("https://x.joinhandshake.com/jobs/900/share_preview"), "900");
  assert.equal(jobIdFromUrl("https://x.joinhandshake.com/stu/jobs"), null);
});

test("labelled reader does not return the label as its own value", () => {
  const d = doc("<div><strong>Location:</strong></div>");
  assert.equal(readLabelled(d, ["location"]), null);
});
