// Exercises the public MusicBee ABI and real named-pipe client without touching
// a music library or playback. Run only when MusicBee's helper is not loaded.
using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using MusicBeePlugin;

class TestHost {
    delegate int ForeignInt();
    delegate float ForeignFloat();
    delegate bool ForeignSetInt(int value);
    delegate bool ForeignSetFloat(float value);
    static Delegate[] keep;
    [STAThread]
    static void Main() {
        int owner = Thread.CurrentThread.ManagedThreadId;
        int position = 12000; float volume = .42f;
        var ui = new Control(); IntPtr uiHandle = ui.Handle;
        Action requireUI = delegate { if (Thread.CurrentThread.ManagedThreadId != owner) throw new Exception("Wrong thread"); };
        keep = new Delegate[] {
            new ForeignInt(delegate { requireUI(); return position; }),
            new ForeignSetInt(delegate(int value) { requireUI(); position=value; return true; }),
            new ForeignInt(delegate { requireUI(); return 3; }),
            new ForeignFloat(delegate { requireUI(); return volume; }),
            new ForeignSetFloat(delegate(float value) { requireUI(); volume=value; return true; }),
            new ForeignInt(delegate { requireUI(); return 240000; }),
            new Plugin.GetHandle(delegate { return uiHandle; })
        };
        int[] slots = {14,15,16,24,25,39,56};
        int header = IntPtr.Size == 8 ? 8 : 4;
        IntPtr table = Marshal.AllocHGlobal(header + 64 * IntPtr.Size);
        for (int i=0;i<64;i++) Marshal.WriteIntPtr(table,header+i*IntPtr.Size,IntPtr.Zero);
        for (int i=0;i<slots.Length;i++) Marshal.WriteIntPtr(table,header+slots[i]*IntPtr.Size,Marshal.GetFunctionPointerForDelegate(keep[i]));
        var plugin = new Plugin(".Test." + System.Diagnostics.Process.GetCurrentProcess().Id); plugin.Initialise(table);
        plugin.ReceiveNotification("",Plugin.NotificationType.PluginStartup);
        var expiry = new System.Windows.Forms.Timer(); expiry.Interval=30000;
        expiry.Tick += delegate { Application.ExitThread(); }; expiry.Start();
        Console.WriteLine("MusicBee ABI test host ready");
        Application.Run();
        plugin.Close(Plugin.PluginCloseReason.MusicBeeClosing);
        expiry.Dispose(); Marshal.FreeHGlobal(table); GC.KeepAlive(keep);
    }
}
