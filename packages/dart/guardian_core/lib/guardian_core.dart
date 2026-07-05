/// Shared Guardian AI domain entities and value objects.
///
/// Pure Dart. Domain code only — no Flutter, no I/O, no app imports.
/// The wire formats mirror the edge device API (ADR-0015); parsing is
/// strict so a malformed box payload fails loudly, never silently.
library;

export 'src/incident_details.dart';
export 'src/notification_message.dart';
export 'src/paired_box.dart';
export 'src/severity.dart';

/// Package version, asserted by the scaffold smoke test.
const String guardianCoreVersion = '0.1.0';
