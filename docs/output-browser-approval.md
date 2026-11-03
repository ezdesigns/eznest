# OUTPUT browser approval

The host owner chooses **Continue with OUTPUT** in Ez Nest. A browser opens to
OUTPUT sign-in and approval. Owners without an OUTPUT shop create one there;
owners with a shop see its name. They compare the short match code and approve.
Ez Nest finishes in the background without asking them to paste a credential.

Pairing does not grant sharing consent or send customer files, job names,
inventory or capacity. The host label and app version identify the computer.
An explicit OUTPUT-off launch setting continues to disable connection setup.

The host keeps a generated redemption code only in memory for ten minutes.
OUTPUT receives its hash. The public approval URL contains only a link UUID.
The authenticated owner approves the displayed OUTPUT shop; Ez Nest then
uses the existing pair exchange and protected credential storage. The UI waits
for OUTPUT to report an authenticated host check-in before saying Connected.

Closing/cancelling the dialog forgets the pending request; it does not disconnect
a computer already paired. Use Settings to inspect or disconnect that connection.
After a restart, expired request, or uncertain exchange result, start a new
request. Manual pairing stays available under **Use a pairing code instead**.

Deployment order:
1. Deploy OUTPUT PR 128 and apply migrations through 0033 in its approved
   environment. Its existing shop-agent feature flag must be enabled.
2. Install the Ez Nest build with output_link.py. It needs no callback listener,
   exposed port, local HTTPS certificate, or shared browser session.
3. Validate a real owner sign-in, create/select existing shop, approve, and host
   check-in. Keep activity and capacity sharing off unless separately authorized.

An older or disabled OUTPUT deployment produces a readable unavailable message;
nesting continues and manual pairing remains available. Live connection has not
been established by the automated tests.

Local verification uses synthetic API responses and temporary app data:
test_output_link, test_output_link_ui, test_output_gate, test_output_pairing and
test_shop_team_ui. Tests include popup blocking, cancellation, rate-bound polling,
response binding, once-only redemption, expiry, host-only endpoints, unchanged
sharing, and both old and new connection controls.
