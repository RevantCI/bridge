// translationCore AI Bridge — Paratext companion plugin.
//
// Real blocker closed here (see docs/BUILD_LOG.md's Phase 7 section):
// engine/tc_ai_bridge/paratext_connector.py's ParatextConnectorClient only ever
// talks to a companion plugin over a Windows named pipe
// (\\.\pipe\translationCoreAIBridge, newline-delimited JSON, protocol version 1)
// — that companion didn't exist anywhere in this repo before this file. This is
// it: a minimal IParatextStartupAutomaticPlugin that starts a named-pipe server
// when Paratext launches and answers get_state / set_reference (create_note is
// intentionally NOT implemented here — Bridge already has a complete, working
// Paratext Notes 1.1 XML writer in tc_ai_bridge/paratext_notes.py that writes
// notes directly to disk without needing this plugin at all; duplicating that
// through a live AddNote() call — which needs an IWriteLock, an
// IScriptureTextSelection, and CommentParagraph objects this session had no way
// to verify against a real running Paratext instance — would be exactly the
// kind of unverified integration this project's own practice warns against).
//
// Every interface member used here (IPluginHost, IVerseRef, IParatextChildState,
// IProject, ParatextInternal.IParatextPlugin, ReferenceChangedHandler,
// SyncReferenceGroup, ...) was confirmed by reflecting into the real
// PluginInterfaces.dll / CorePluginInterfaces.dll installed at
// "C:\Program Files\Paratext 9" on the dev machine this was built on — not
// copied from documentation. See README.md in this folder for what has and has
// not actually been verified end-to-end (this plugin has never been loaded by a
// running Paratext instance as of this commit).

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using Paratext.PluginInterfaces;

namespace TranslationCoreAIBridge
{
    public class TranslationCoreAIBridgePlugin : IParatextStartupAutomaticPlugin
    {
        public const string PipeName = "translationCoreAIBridge";
        public const int ProtocolVersion = 1;

        private IPluginHost _host;
        private Thread _serverThread;
        private volatile bool _running;
        private readonly object _stateLock = new object();
        private int _stateRevision;
        private string _lastEvent = "";
        private string _lastOriginId = "";

        // -- Paratext.PluginInterfaces.ParatextInternal.IParatextPlugin ----------------

        public string Name { get { return "translationCore AI Bridge Connector"; } }
        public Version Version { get { return new Version(1, 0, 0, 0); } }
        public string VersionString { get { return "1.0.0"; } }
        public string Publisher { get { return "Bridge"; } }

        public string GetDescription(string locale)
        {
            return "Local named-pipe bridge letting the Bridge desktop app read the "
                + "current Paratext reference and push its own navigation into Paratext. "
                + "No network access; communicates only over a local Windows named pipe.";
        }

        public IDataFileMerger GetMerger(IPluginHost host, string dataIdentifier)
        {
            // This plugin stores no per-project data files of its own (state lives only
            // in memory for the life of the Paratext process), so there is nothing to merge.
            return null;
        }

        // -- IParatextStartupAutomaticPlugin --------------------------------------------

        public void Run(IPluginHost host)
        {
            _host = host;
            host.VerseRefChanged += OnVerseRefChanged;
            host.ShuttingDown += OnShuttingDown;
            _running = true;
            _serverThread = new Thread(ServerLoop);
            _serverThread.IsBackground = true;
            _serverThread.Name = "TranslationCoreAIBridge-Pipe";
            _serverThread.Start();
            LogSafe("translationCore AI Bridge pipe server starting on \\\\.\\pipe\\{0}", PipeName);
        }

        private void OnShuttingDown(object sender, CancelEventArgs e)
        {
            _running = false;
            // Unblock a pending WaitForConnection() by connecting to ourselves once.
            try
            {
                using (var client = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut))
                {
                    client.Connect(50);
                }
            }
            catch
            {
                // Best effort only — if the pipe server thread is between accept cycles
                // this simply does nothing, and the thread exits with the process anyway
                // since it is a background thread.
            }
        }

        private void OnVerseRefChanged(IPluginHost sender, IVerseRef newVerseRef, SyncReferenceGroup syncReferenceGroup)
        {
            lock (_stateLock)
            {
                _stateRevision++;
                _lastEvent = "verseRefChanged";
            }
        }

        // -- Named-pipe server loop ------------------------------------------------------

        private void ServerLoop()
        {
            while (_running)
            {
                try
                {
                    using (var server = new NamedPipeServerStream(
                        PipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.None))
                    {
                        server.WaitForConnection();
                        if (!_running)
                        {
                            break;
                        }
                        HandleConnection(server);
                    }
                }
                catch (Exception ex)
                {
                    LogSafe("Pipe server error: {0}", ex.Message);
                    Thread.Sleep(250);
                }
            }
        }

        private void HandleConnection(NamedPipeServerStream server)
        {
            var serializer = new JavaScriptSerializer();
            string requestId = null;
            try
            {
                string line = ReadLine(server);
                if (line == null)
                {
                    return;
                }
                Dictionary<string, object> request;
                try
                {
                    request = serializer.DeserializeObject(line) as Dictionary<string, object>;
                }
                catch (Exception parseEx)
                {
                    WriteResponse(server, serializer, ErrorResponse(null, "Invalid JSON request: " + parseEx.Message));
                    return;
                }
                if (request == null)
                {
                    WriteResponse(server, serializer, ErrorResponse(null, "Request was not a JSON object."));
                    return;
                }
                requestId = GetString(request, "id");
                string action = GetString(request, "action");
                var payload = request.ContainsKey("payload") ? request["payload"] as Dictionary<string, object> : null;
                if (payload == null)
                {
                    payload = new Dictionary<string, object>();
                }

                Dictionary<string, object> response;
                switch (action)
                {
                    case "get_state":
                        response = HandleGetState(requestId);
                        break;
                    case "set_reference":
                        response = HandleSetReference(requestId, payload);
                        break;
                    case "create_note":
                        response = ErrorResponse(requestId,
                            "create_note is intentionally not implemented by this plugin — "
                            + "Bridge writes Paratext Notes 1.1 XML directly instead.");
                        break;
                    default:
                        response = ErrorResponse(requestId, "Unknown action: " + action);
                        break;
                }
                WriteResponse(server, serializer, response);
            }
            catch (Exception ex)
            {
                try
                {
                    WriteResponse(server, serializer, ErrorResponse(requestId, ex.Message));
                }
                catch
                {
                    // The pipe may already be broken; nothing more to do for this connection.
                }
            }
        }

        private Dictionary<string, object> HandleGetState(string requestId)
        {
            var response = BaseResponse(requestId);
            IParatextChildState activeWindow = null;
            try
            {
                activeWindow = _host.ActiveWindowState;
            }
            catch
            {
                // No active window state is a normal condition (e.g. no text window
                // focused yet), not a protocol error — fields below simply stay empty.
            }

            string userName = "";
            try
            {
                if (_host.UserInfo != null)
                {
                    userName = _host.UserInfo.Name ?? "";
                }
            }
            catch
            {
            }

            IVerseRef verseRef = null;
            IProject project = null;
            SyncReferenceGroup syncGroup = SyncReferenceGroup.None;
            if (activeWindow != null)
            {
                try { verseRef = activeWindow.VerseRef; } catch { }
                try { project = activeWindow.Project; } catch { }
                try { syncGroup = activeWindow.SyncReferenceGroup; } catch { }
            }

            response["user"] = userName;
            response["project_name"] = project != null ? (project.ShortName ?? "") : "";
            response["project_id"] = project != null ? (project.ID ?? "") : "";
            response["project_language"] = project != null ? (project.LanguageName ?? "") : "";
            response["reference"] = verseRef != null
                ? string.Format("{0} {1}:{2}", verseRef.BookCode, verseRef.ChapterNum, verseRef.VerseNum)
                : "";
            response["sync_group"] = syncGroup.ToString();
            response["selected_text"] = "";
            response["selection_reference"] = "";
            response["before_context"] = "";
            response["after_context"] = "";
            response["selection_offset"] = -1;
            response["paratext_version"] = SafeApplicationVersion();
            response["plugin_version"] = VersionString;
            lock (_stateLock)
            {
                response["state_revision"] = _stateRevision;
                response["last_event"] = _lastEvent;
                response["last_origin_id"] = _lastOriginId;
            }
            response["capabilities"] = new List<object> { "get_state", "set_reference" };
            return response;
        }

        private Dictionary<string, object> HandleSetReference(string requestId, Dictionary<string, object> payload)
        {
            string reference = GetString(payload, "reference");
            string originId = GetString(payload, "origin_id");
            if (string.IsNullOrEmpty(reference))
            {
                return ErrorResponse(requestId, "set_reference requires a non-empty 'reference'.");
            }
            IVerseRef parsed = ParseReference(reference);
            if (parsed == null)
            {
                return ErrorResponse(requestId, "Could not parse reference: " + reference);
            }
            _host.SetReferenceForSyncGroup(parsed, SyncReferenceGroup.None);
            lock (_stateLock)
            {
                _stateRevision++;
                _lastEvent = "set_reference";
                _lastOriginId = originId ?? "";
            }
            var response = BaseResponse(requestId);
            response["reference"] = reference;
            return response;
        }

        // -- helpers ----------------------------------------------------------------------

        private IVerseRef ParseReference(string reference)
        {
            // "BOOK C:V", e.g. "TIT 1:1" - the same normalized shape
            // tc_ai_bridge/navigation.py's normalize_reference() produces. Uses
            // IVersification.CreateReference(string) - Paratext's own reference parser -
            // rather than hand-parsing the book code into a book number ourselves.
            try
            {
                IVerseRef current = null;
                try { current = _host.ActiveWindowState != null ? _host.ActiveWindowState.VerseRef : null; } catch { }
                IVersification versification = current != null
                    ? current.Versification
                    : _host.GetStandardVersification(StandardScrVersType.English);
                return versification.CreateReference(reference.Trim());
            }
            catch
            {
                return null;
            }
        }

        private string SafeApplicationVersion()
        {
            try { return _host.ApplicationVersion.ToString(); } catch { return ""; }
        }

        private void LogSafe(string format, params object[] args)
        {
            try
            {
                if (_host != null)
                {
                    _host.Log(this, format, args);
                }
            }
            catch
            {
                // Logging must never be allowed to crash the plugin.
            }
        }

        private static Dictionary<string, object> BaseResponse(string requestId)
        {
            var response = new Dictionary<string, object>();
            response["id"] = requestId;
            response["protocol"] = ProtocolVersion;
            response["ok"] = true;
            return response;
        }

        private static Dictionary<string, object> ErrorResponse(string requestId, string message)
        {
            var response = new Dictionary<string, object>();
            response["id"] = requestId;
            response["protocol"] = ProtocolVersion;
            response["ok"] = false;
            response["error"] = message;
            return response;
        }

        private static string GetString(Dictionary<string, object> dict, string key)
        {
            object value;
            if (dict != null && dict.TryGetValue(key, out value) && value != null)
            {
                return Convert.ToString(value);
            }
            return "";
        }

        // The Python client writes one JSON line and reads until '\n' (see
        // paratext_connector.py's _exchange) — read/write must match that exactly,
        // not a length-prefixed or fixed-size framing.
        private static string ReadLine(Stream stream)
        {
            var buffer = new List<byte>();
            int b;
            while ((b = stream.ReadByte()) != -1)
            {
                if (b == '\n')
                {
                    break;
                }
                buffer.Add((byte)b);
                if (buffer.Count > 2000000)
                {
                    throw new IOException("Request exceeded safety limit.");
                }
            }
            if (buffer.Count == 0 && b == -1)
            {
                return null;
            }
            return Encoding.UTF8.GetString(buffer.ToArray());
        }

        private static void WriteResponse(Stream stream, JavaScriptSerializer serializer, Dictionary<string, object> response)
        {
            string json = serializer.Serialize(response);
            byte[] bytes = Encoding.UTF8.GetBytes(json + "\n");
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }
    }
}
