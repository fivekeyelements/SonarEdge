// Sonar Edge's MusicBee bridge. Original implementation using MusicBee's public
// plugin ABI: https://getmusicbee.com/help/api/ . No network listener or shell.
using System;
using System.Collections.Generic;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace MusicBeePlugin {
    public class Plugin {
        public enum PluginType { General = 1 }
        public enum ReceiveNotificationFlags { PlayerEvents = 1 }
        public enum NotificationType { PluginStartup = 0, TrackChanged = 1, MusicBeeStarted = 34 }
        public enum PluginCloseReason { MusicBeeClosing = 1, UserDisabled = 2, StopNoUnload = 3 }
        [StructLayout(LayoutKind.Sequential)]
        public class PluginInfo {
            public short PluginInfoVersion = 1;
            public PluginType Type = PluginType.General;
            public string Name = "Sonar Edge";
            public string Description = "Playback progress, seeking and player volume for Sonar Edge.";
            public string Author = "Kagi Software";
            public string TargetApplication = "";
            public short VersionMajor = 1, VersionMinor = 4, Revision = 0;
            public short MinInterfaceVersion = 41, MinApiRevision = 53;
            public ReceiveNotificationFlags ReceiveNotifications = ReceiveNotificationFlags.PlayerEvents;
            public int ConfigurationPanelHeight = 0;
        }
        public delegate int GetInt();
        public delegate float GetFloat();
        public delegate IntPtr GetHandle();
        public delegate bool SetInt(int value);
        public delegate bool SetFloat(float value);
        GetInt position, duration, playState;
        GetFloat volume;
        SetInt seek;
        SetFloat setVolume;
        Control ui;
        System.Windows.Forms.Timer timer;
        Thread worker;
        bool ownsUI;
        volatile bool stopping;
        volatile string snapshot = "{\"connected\":false}";
        NamedPipeServerStream listener;
        readonly object pipeLock = new object();
        readonly string pipeSuffix;
        public Plugin() : this("") { }
        internal Plugin(string testSuffix) { pipeSuffix = testSuffix; }

        T Bind<T>(IntPtr table, int slot) where T : class {
            // Two Int16 header fields, then naturally aligned function pointers.
            int header = IntPtr.Size == 8 ? 8 : 4;
            IntPtr pointer = Marshal.ReadIntPtr(table, header + slot * IntPtr.Size);
            if (pointer == IntPtr.Zero) throw new InvalidOperationException("MusicBee API unavailable");
            Delegate original = Marshal.GetDelegateForFunctionPointer(pointer, typeof(T));
            if (original is T) return original as T;
            // A pointer originating from a managed MusicBee delegate can resolve
            // to that original delegate type, including MusicBee's own enums.
            // Adapt its result instead of silently storing a null delegate.
            if (typeof(T) == typeof(GetInt)) return new GetInt(delegate { return Convert.ToInt32(original.DynamicInvoke()); }) as T;
            if (typeof(T) == typeof(GetFloat)) return new GetFloat(delegate { return Convert.ToSingle(original.DynamicInvoke()); }) as T;
            if (typeof(T) == typeof(SetInt)) return new SetInt(delegate(int value) { return Convert.ToBoolean(original.DynamicInvoke(value)); }) as T;
            if (typeof(T) == typeof(SetFloat)) return new SetFloat(delegate(float value) { return Convert.ToBoolean(original.DynamicInvoke(value)); }) as T;
            if (typeof(T) == typeof(GetHandle)) return new GetHandle(delegate { return (IntPtr)original.DynamicInvoke(); }) as T;
            throw new InvalidOperationException("Unsupported MusicBee function signature");
        }
        public PluginInfo Initialise(IntPtr table) {
            position = Bind<GetInt>(table, 14); seek = Bind<SetInt>(table, 15);
            playState = Bind<GetInt>(table, 16); volume = Bind<GetFloat>(table, 24);
            setVolume = Bind<SetFloat>(table, 25); duration = Bind<GetInt>(table, 39);
            ui = Control.FromHandle(Bind<GetHandle>(table,56)());
            ownsUI = ui == null;
            if (ownsUI) { ui = new Control(); IntPtr handle = ui.Handle; }
            stopping = false;
            Action start = delegate {
                timer = new System.Windows.Forms.Timer(); timer.Interval = 250;
                timer.Tick += delegate { Capture(); }; timer.Start(); Capture();
            };
            if (ui.InvokeRequired) ui.BeginInvoke(start); else start();
            worker = new Thread(Serve); worker.IsBackground = true; worker.Name = "Sonar Edge MusicBee"; worker.Start();
            return new PluginInfo();
        }
        public bool Configure(IntPtr panel) { return false; }
        public void SaveSettings() { }
        public void Uninstall() { }
        public void ReceiveNotification(string sourceFileUrl, NotificationType type) {
            if (ui != null && !ui.IsDisposed) {
                if (ui.InvokeRequired) ui.BeginInvoke((Action)Capture); else Capture();
            }
        }
        void Capture() {
            if (stopping) return;
            try {
                double seconds = Math.Max(0, duration()) / 1000.0;
                var state = new Dictionary<string, object> {
                    {"connected", true}, {"version", "1.4.0"},
                    {"position", Math.Min(seconds, Math.Max(0, position()) / 1000.0)},
                    {"duration", seconds}, {"volume", Math.Max(0, Math.Min(1, volume()))},
                    {"playing", playState() == 3}
                };
                snapshot = new JavaScriptSerializer().Serialize(state);
            } catch (Exception error) { snapshot = new JavaScriptSerializer().Serialize(new { connected = false, error = error.GetType().Name }); }
        }
        string Command(Dictionary<string, object> request) {
            object actionValue;
            if (!request.TryGetValue("action", out actionValue)) throw new ArgumentException("Missing action");
            string action = actionValue as string;
            if (action == "state") return snapshot;
            if (action != "volume" && action != "seek") throw new ArgumentException("Unknown action");
            object raw;
            if (!request.TryGetValue("value", out raw) || raw is bool || raw is string) throw new ArgumentException("Invalid value");
            double value = Convert.ToDouble(raw);
            if (double.IsNaN(value) || double.IsInfinity(value) || value < 0 || (action == "volume" && value > 1)) throw new ArgumentException("Out of range");
            // All MusicBee API calls run on its UI thread. Expired queued commands
            // are discarded, so a timeout cannot cause an unexpected later edit.
            int expired = 0; string result = null; Exception failure = null;
            using (var done = new ManualResetEvent(false)) {
                ui.BeginInvoke((Action)delegate {
                    if (Interlocked.CompareExchange(ref expired, 0, 0) != 0) return;
                    try {
                        bool ok;
                        if (action == "volume") ok = setVolume((float)value);
                        else {
                            int length = duration();
                            if (length <= 0 || value * 1000 > length) throw new ArgumentException("Track is not seekable");
                            ok = seek((int)Math.Round(value * 1000));
                        }
                        if (!ok) throw new InvalidOperationException("MusicBee rejected the command");
                        Capture(); result = snapshot;
                    } catch (Exception error) { failure = error; }
                    finally { try { done.Set(); } catch (ObjectDisposedException) { } }
                });
                if (!done.WaitOne(700)) { Interlocked.Exchange(ref expired, 1); throw new TimeoutException("MusicBee is busy"); }
            }
            if (failure != null) throw failure;
            return result;
        }
        void Serve() {
            SecurityIdentifier user = WindowsIdentity.GetCurrent().User;
            var security = new PipeSecurity();
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new PipeAccessRule(user, PipeAccessRights.FullControl, AccessControlType.Allow));
            string name = "SonarEdge.MusicBee." + user.Value + pipeSuffix;
            while (!stopping) {
                try {
                    using (var pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1,
                            PipeTransmissionMode.Message, PipeOptions.Asynchronous, 4096, 16384, security)) {
                        lock (pipeLock) { if (stopping) return; listener = pipe; }
                        pipe.WaitForConnection();
                        byte[] bytes = new byte[4096];
                        var read = pipe.ReadAsync(bytes, 0, bytes.Length);
                        if (!read.Wait(1000) || !pipe.IsMessageComplete) continue;
                        string response;
                        try {
                            var json = new JavaScriptSerializer(); json.MaxJsonLength = 4096;
                            var request = json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(bytes, 0, read.Result));
                            response = Command(request);
                        } catch (Exception error) {
                            response = new JavaScriptSerializer().Serialize(new { error = error.Message });
                        }
                        byte[] reply = Encoding.UTF8.GetBytes(response);
                        var write = pipe.WriteAsync(reply, 0, reply.Length); write.Wait(1000);
                    }
                } catch { if (!stopping) Thread.Sleep(150); }
                finally { lock (pipeLock) { listener = null; } }
            }
        }
        public void Close(PluginCloseReason reason) {
            stopping = true;
            lock (pipeLock) { if (listener != null) listener.Dispose(); }
            if (timer != null) { timer.Stop(); timer.Dispose(); }
            if (ownsUI && ui != null) ui.Dispose();
        }
    }
}
