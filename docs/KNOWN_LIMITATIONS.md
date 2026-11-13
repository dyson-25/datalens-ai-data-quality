# Known limitations

Initial implementation in progress; no application acceptance criteria claimed complete.

- Docker executable absent at environment inspection: image build pending an available Docker engine.
- No Render account/deployment authorization available: prepare configuration, do not claim live deployment.
- Free-provider service availability is external and cannot be guaranteed; core must work offline.
- In-process jobs cannot survive restart. Public demonstration storage is ephemeral.
- Available system memory is shared; conservative row/column/upload limits do not guarantee capacity.
