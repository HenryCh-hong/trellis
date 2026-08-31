/**
 * Hand-authored fixtures.
 *
 * Deliberately NOT fetched from Handshake: their robots.txt is Disallow:/ and
 * their terms forbid bulk collection. These reproduce the *shapes* documented
 * in data/harvest/recon/handshake-integration.json — a legacy knockout page,
 * a JSON-LD page, and a sparse page where most fields are simply absent.
 */

export const KNOCKOUT_JOB = `
<html><head><title>Residential SOAR Specialist | Trilogy, Inc. | Handshake</title></head>
<body>
  <div data-knockout-props='{"location_names":["6701 South Elizabeth Street, Chicago, Illinois 60636, United States"],"locationable_id":8000000,"locationable_type":"Job"}'>
    <h1 class="card-heading-title">Residential SOAR Specialist</h1>
    <div class="card-heading-subtitle"><a class="no-underline" href="/employers/14571">Trilogy, Inc.</a></div>
    <div><strong>Job Type:</strong> Full-Time</div>
    <div class="sanitized-html-container">
      <h2>Overview</h2><p>Support residents through the SOAR process.</p>
      <div class="ql-align-center"><strong>$22.83 /Hr.</strong></div>
      <h2>Qualifications</h2><ul><li>Bachelor's degree required</li></ul>
      <h2>Preferred</h2><ul><li>Experience with case management is a plus</li></ul>
    </div>
    <button>Apply Externally</button>
  </div>
</body></html>`;

export const JSONLD_JOB = `
<html><head><title>Undergraduate Research Assistant | Stanford | Handshake</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Undergraduate Research Assistant",
 "hiringOrganization":{"@type":"Organization","name":"Stanford University"},
 "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Stanford"}},
 "datePosted":"2026-08-01","validThrough":"2026-09-15",
 "description":"Assist with data collection and analysis."}
</script></head>
<body><h1>Undergraduate Research Assistant</h1><button>Quick Apply</button></body></html>`;

export const SPARSE_JOB = `
<html><head><title>Library Shelving Assistant | Handshake</title></head>
<body><h1>Library Shelving Assistant</h1></body></html>`;

export const LIST_PAGE = `
<html><body>
  <article><a href="/jobs/111">Student Technical Consultant</a>
    <a href="/employers/5">Stanford Student Affairs</a></article>
  <article><a href="/jobs/222">Dining Services Associate</a>
    <a href="/employers/6">Stanford R&amp;DE</a></article>
  <article><a href="/jobs/111">Student Technical Consultant (duplicate link)</a></article>
  <a href="/jobs/333"></a>
</body></html>`;
