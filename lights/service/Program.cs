// Keyglow Lights: the lighting of RGB memory sticks, for Keyglow.
//
// A memory stick's lights hang off the PC's SMBus, which only a driver can reach. This small
// service reaches it through PawnIO - the driver FanControl, LibreHardwareMonitor and OpenRGB use,
// with the SMBus modules signed for it that LibreHardwareMonitor's library carries - and sets the
// effect on Corsair's RGB memory (Vengeance RGB, Dominator; DDR4 and DDR5).
//
// Nothing listens: no port, no pipe. Keyglow lays what it wants in a block of shared memory
// (Global\KeyglowLightsAsk, which signed-in users may write) and sets an event
// (Global\KeyglowLightsWanted); the service answers in another (Global\KeyglowLights, which they
// may only read). It stops itself after a minute without being asked, and Keyglow starts it again
// when it next wants something: signed-in users may start it and see whether it runs, nothing more
// (the setup gives it that).
//
// What a user can ask for is narrow: an effect, its speed, brightness and colours, for the memory
// it found. Only addresses that answered as Corsair memory - its signature, then its device block
// with Corsair's vendor id and a matching checksum - are ever written to.
//
//   KeyglowLights.exe                       as the service (started by Windows)
//   KeyglowLights.exe --console NAME [--fake] [--idle S]
//                                           for tests: as the user, with Local\NAME,
//                                           Local\NAMEAsk and Local\NAMEWanted; --fake: two
//                                           stand-in sticks instead of the SMBus

using System.ComponentModel;
using System.Globalization;
using System.Runtime.InteropServices;
using System.ServiceProcess;

namespace KeyglowLights;

public static class Program
{
    public const string ServiceName = "KeyglowLights";
    public const string StatusName = @"Global\KeyglowLights";
    public const string AskName = @"Global\KeyglowLightsAsk";
    public const string WantedName = @"Global\KeyglowLightsWanted";
    public const int IdleMs = 60_000;          // stops after this long without being asked

    public static int Main(string[] args)
    {
        if (args.Length >= 2 && args[0] == "--console")
            return RunAsUser(args);
        ServiceBase.Run(new LightsService());
        return 0;
    }

    static int RunAsUser(string[] args)
    {
        string name = args[1];
        bool fake = args.Contains("--fake");
        int idle = IdleMs;
        int at = Array.IndexOf(args, "--idle");
        if (at > 0 && at + 1 < args.Length)
            idle = (int)(double.Parse(args[at + 1], CultureInfo.InvariantCulture) * 1000);
        using var blocks = new Blocks($@"Local\{name}", $@"Local\{name}Ask", $@"Local\{name}Wanted", forEveryone: false);
        Func<Opened> open = fake ? FakeBus.Open : PawnIoBus.OpenAll;
        Loop.Run(blocks, open, idle, () => false);
        return 0;
    }
}

public enum Status
{
    Ready = 0,          // memory found; what is asked for is set on it
    NoPawnIo = 1,       // PawnIO isn't installed, so the SMBus can't be reached
    NoMemory = 2,       // the SMBus was reached, but no RGB memory Keyglow knows answered on it
    Failed = 3,         // something went wrong (the message says what)
    Starting = 4,       // looking
}

/// <summary>An effect to set, as Keyglow asks for it.</summary>
public sealed record Effect(byte Mode, byte Speed, bool Random, byte Direction, byte Brightness,
                            byte[] A, byte[] B, byte[] Leds)
{
    // Corsair's own effects, by its numbers
    public const byte ColorShift = 0x00, ColorPulse = 0x01, RainbowWave = 0x03, ColorWave = 0x04, Visor = 0x05,
                      Rain = 0x06, Marquee = 0x07, Rainbow = 0x08, Sequential = 0x09, Static = 0x10;
    public static readonly byte[] Modes =
        [ColorShift, ColorPulse, RainbowWave, ColorWave, Visor, Rain, Marquee, Rainbow, Sequential, Static];
    public const int MaxLeds = 12;

    public string? Problem() =>
        !Modes.Contains(Mode) ? $"effect {Mode} is not one the memory has" :
        Speed > 2 ? "speed is 0, 1 or 2" :
        Direction > 3 ? "direction is 0 to 3" :
        A.Length != 3 || B.Length != 3 || Leds.Length != MaxLeds * 3 ? "colours are cut short" : null;
}

public sealed record Opened(List<ISmbus> Buses, Status Status, string Message);

/// <summary>Opened, it looks for memory; asked, it sets the effect; not asked for idleMs, it
/// returns - and the service stops.</summary>
public static class Loop
{
    public static void Run(Blocks blocks, Func<Opened> open, int idleMs, Func<bool> stopping)
    {
        blocks.WriteStatus(Status.Starting, [], 0, 0, "");
        Opened opened;
        try
        {
            opened = open();
        }
        catch (Exception error)
        {
            opened = new Opened([], Status.Failed, error.Message);
        }
        List<Module> modules = [];
        try
        {
            var status = opened.Status;
            string message = opened.Message;
            try
            {
                if (opened.Buses.Count > 0)
                {
                    modules = Corsair.Find(opened.Buses);
                    status = modules.Count > 0 ? Status.Ready : Status.NoMemory;
                }
            }
            catch (Exception error)
            {
                (status, message) = (Status.Failed, error.Message);
            }
            uint done = 0, failed = 0;
            blocks.WriteStatus(status, modules, done, failed, message);
            while (!stopping())
            {
                var asked = blocks.ReadAsk();
                if (asked is var (number, effect) && number != done && number != failed)
                {
                    string? problem = effect.Problem();
                    if (problem is null && modules.Count == 0)
                        problem = "no memory to set";
                    if (problem is null)
                        problem = modules.Select(m => Corsair.Apply(m, effect)).FirstOrDefault(p => p is not null);
                    if (problem is null)
                        done = number;
                    else
                        failed = number;
                    blocks.WriteStatus(status, modules, done, failed, problem ?? "");
                    continue;                       // something newer may have come meanwhile
                }
                if (!blocks.WaitWanted(idleMs) || stopping())
                    return;
            }
        }
        finally
        {
            foreach (var bus in opened.Buses)
                bus.Dispose();
        }
    }
}

// --- the SMBus ------------------------------------------------------------------------------

public interface ISmbus : IDisposable
{
    string Name { get; }
    /// <summary>A byte from a register, or -1 if nothing answered.</summary>
    int ReadByte(byte address, byte command);
    bool WriteByte(byte address, byte command, byte value);
    /// <summary>Held while a whole exchange with one stick goes, so no other program's falls in
    /// the middle of it.</summary>
    IDisposable Lock();
}

/// <summary>The convention HWiNFO, OpenRGB and LibreHardwareMonitor follow: whoever uses the SMBus
/// holds this mutex meanwhile.</summary>
sealed class SmbusMutex : IDisposable
{
    const string Name = @"Global\Access_SMBUS.HTP.Method";
    // Everyone may wait on it and release it, as the other programs expect to.
    const string Sddl = "D:(A;;GA;;;WD)";
    static IntPtr _handle;

    readonly bool _held;

    SmbusMutex(bool held) => _held = held;

    public static SmbusMutex Take(int ms = 1000)
    {
        if (_handle == IntPtr.Zero)
            _handle = Native.Create(Sddl, sa => Native.CreateMutexW(sa, false, Name));
        uint result = Native.WaitForSingleObject(_handle, (uint)ms);
        if (result != 0 && result != 0x80)          // WAIT_OBJECT_0, WAIT_ABANDONED
            throw new System.TimeoutException("another program kept the SMBus busy");
        return new SmbusMutex(true);
    }

    public void Dispose()
    {
        if (_held)
            Native.ReleaseMutex(_handle);
    }
}

/// <summary>An SMBus reached through PawnIO, with one of the signed modules
/// LibreHardwareMonitor's library carries.</summary>
public sealed class PawnIoBus : ISmbus
{
    const int SmbusRead = 1, SmbusWrite = 0, SizeByteData = 2;

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int OpenFn(out IntPtr handle);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int LoadFn(IntPtr handle, byte[] blob, UIntPtr size);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int ExecuteFn(IntPtr handle, [MarshalAs(UnmanagedType.LPStr)] string name, ulong[] input,
                           UIntPtr inSize, ulong[] output, UIntPtr outSize, out UIntPtr returned);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int CloseFn(IntPtr handle);

    static OpenFn? _open;
    static LoadFn? _load;
    static ExecuteFn? _execute;
    static CloseFn? _close;

    IntPtr _handle;
    public string Name { get; }

    PawnIoBus(IntPtr handle, string name)
    {
        _handle = handle;
        Name = name;
    }

    static string? Library()
    {
        string? folder = null;
        try
        {
            using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO");
            folder = key?.GetValue("InstallLocation") as string;
        }
        catch (Exception) { }
        folder ??= Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "PawnIO");
        string path = Path.Combine(folder, "PawnIOLib.dll");
        return File.Exists(path) ? path : null;
    }

    static bool Bind()
    {
        if (_execute is not null)
            return true;
        string? path = Library();
        if (path is null)
            return false;
        IntPtr lib = NativeLibrary.Load(path);
        _open = Marshal.GetDelegateForFunctionPointer<OpenFn>(NativeLibrary.GetExport(lib, "pawnio_open"));
        _load = Marshal.GetDelegateForFunctionPointer<LoadFn>(NativeLibrary.GetExport(lib, "pawnio_load"));
        _close = Marshal.GetDelegateForFunctionPointer<CloseFn>(NativeLibrary.GetExport(lib, "pawnio_close"));
        _execute = Marshal.GetDelegateForFunctionPointer<ExecuteFn>(NativeLibrary.GetExport(lib, "pawnio_execute"));
        return true;
    }

    static byte[]? Module(string file)
    {
        var assembly = typeof(LibreHardwareMonitor.Hardware.Computer).Assembly;
        using var stream = assembly.GetManifestResourceStream($"LibreHardwareMonitor.Resources.PawnIo.{file}");
        if (stream is null)
            return null;
        using var copy = new MemoryStream();
        stream.CopyTo(copy);
        return copy.ToArray();
    }

    /// <summary>A handle with the module loaded, or null where the module doesn't fit this PC.</summary>
    static IntPtr Start(string file, ref int refused)
    {
        byte[]? blob = Module(file);
        if (blob is null)
            return IntPtr.Zero;
        int result = _open!(out IntPtr handle);
        if (result != 0)
        {
            if (result == unchecked((int)0x80070005))       // E_ACCESSDENIED: not run as the system
                refused++;
            return IntPtr.Zero;
        }
        if (_load!(handle, blob, (UIntPtr)blob.Length) != 0)
        {
            _close!(handle);
            return IntPtr.Zero;
        }
        return handle;
    }

    ulong[]? Execute(string function, ulong[] input, int outputs)
    {
        var output = new ulong[Math.Max(outputs, 1)];
        int result = _execute!(_handle, function, input, (UIntPtr)input.Length, output, (UIntPtr)outputs, out _);
        return result == 0 ? output : null;
    }

    /// <summary>The PC's memory SMBuses: AMD's two ports, or Intel's one.</summary>
    public static Opened OpenAll()
    {
        if (!Bind())
            return new Opened([], Status.NoPawnIo, "PawnIO is not installed");
        var buses = new List<ISmbus>();
        int refused = 0;
        for (int port = 0; port < 2; port++)
        {
            IntPtr handle = Start("SmbusPIIX4.bin", ref refused);
            if (handle == IntPtr.Zero)
                continue;
            var bus = new PawnIoBus(handle, $"AMD SMBus port {port}");
            bool selected;
            using (SmbusMutex.Take())
                selected = bus.Execute("ioctl_piix4_port_sel", [(ulong)port], 1) is not null;
            if (selected && bus.ForMemory())
                buses.Add(bus);
            else
                bus.Dispose();
        }
        IntPtr intel = Start("SmbusI801.bin", ref refused);
        if (intel != IntPtr.Zero)
        {
            var bus = new PawnIoBus(intel, "Intel SMBus");
            if (bus.ForMemory())
                buses.Add(bus);
            else
                bus.Dispose();
        }
        if (buses.Count > 0)
            return new Opened(buses, Status.Ready, "");
        return refused > 0
            ? new Opened([], Status.Failed, "PawnIO refused: the service must run as the system")
            : new Opened([], Status.NoMemory, "no SMBus PawnIO knows on this PC");
    }

    /// <summary>Whether the bus is the chipset's own, where memory sits (AMD's or Intel's).</summary>
    bool ForMemory()
    {
        ulong[]? identity = Execute("ioctl_identity", [0], 3);
        if (identity is null)
            return false;
        int vendor = (int)(identity[2] & 0xFFFF);
        return vendor == 0x1022 || vendor == 0x8086;
    }

    int Transfer(byte address, int readWrite, byte command, byte value)
    {
        var input = new ulong[9];
        input[0] = address;
        input[1] = (ulong)readWrite;
        input[2] = command;
        input[3] = SizeByteData;
        input[4] = value;                           // the data's first byte: i2c_smbus_data.byte
        ulong[]? output = Execute("ioctl_smbus_xfer", input, 5);
        return output is null ? -1 : (int)(output[0] & 0xFF);
    }

    public int ReadByte(byte address, byte command) => Transfer(address, SmbusRead, command, 0);

    public bool WriteByte(byte address, byte command, byte value) =>
        Transfer(address, SmbusWrite, command, value) >= 0;

    public IDisposable Lock() => SmbusMutex.Take();

    public void Dispose()
    {
        if (_handle != IntPtr.Zero)
            _close?.Invoke(_handle);
        _handle = IntPtr.Zero;
    }
}

// --- Corsair's memory -----------------------------------------------------------------------

public sealed record Module(ISmbus Bus, int BusIndex, byte Address, ushort Pid, int Leds, bool Reversed,
                            byte Protocol, string Firmware);

/// <summary>Corsair's RGB memory controller, as OpenRGB documents it (CorsairDRAMController):
/// a byte-wide buffer filled through register 0x20 and checked by a CRC-8 the stick works out
/// itself, then applied by naming the buffer in 0x82.</summary>
public static class Corsair
{
    public const ushort Vendor = 0x1B1C;
    const byte ResetBuffer = 0x0B, SetData = 0x20, Start = 0x21, Status = 0x30, GetData = 0x40, Checksum = 0x42,
               DeviceInfo = 0x61, ApplyBuffer = 0x82;
    const byte EffectBuffer = 1, ColourBuffer = 2;

    // Where sticks answer: DDR5's 0x58-0x5F, DDR4's 0x18-0x1F.
    static readonly byte[] Addresses = [0x58, 0x59, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
                                        0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F];

    public static List<Module> Find(IList<ISmbus> buses)
    {
        var found = new List<Module>();
        for (int b = 0; b < buses.Count; b++)
        {
            var bus = buses[b];
            foreach (byte address in Addresses)
            {
                using (bus.Lock())
                {
                    if (!Answers(bus, address))
                        continue;
                    byte[]? info = Info(bus, address);
                    if (info is null || (info[0] | info[1] << 8) != Vendor)
                        continue;
                    ushort pid = (ushort)(info[2] | info[3] << 8);
                    var (leds, reversed) = Shape(pid);
                    string firmware = $"{info[9]}.{info[8]}.{info[10] | info[11] << 8}";
                    found.Add(new Module(bus, b, address, pid, leds, reversed, info[28], firmware));
                }
            }
        }
        return found;
    }

    static bool Answers(ISmbus bus, byte address)
    {
        int a = bus.ReadByte(address, 0x43);
        if (a is not (0x1A or 0x1B or 0x1C))
            return false;
        int b = bus.ReadByte(address, 0x44);
        return b is 0x01 or 0x03 or 0x04;
    }

    static byte[]? Info(ISmbus bus, byte address)
    {
        if (!bus.WriteByte(address, DeviceInfo, 0) || !bus.WriteByte(address, Start, 0))
            return null;
        var info = new byte[32];
        for (int i = 0; i < info.Length; i++)
        {
            int value = bus.ReadByte(address, GetData);
            if (value < 0)
                return null;
            info[i] = (byte)value;
        }
        return bus.ReadByte(address, Checksum) == Crc8(info) ? info : null;
    }

    /// <summary>How many lights a stick has, and whether they run bottom to top, by its product id.</summary>
    public static (int Leds, bool Reversed) Shape(ushort pid) => (pid >> 8) switch
    {
        0x02 or 0x06 or 0x08 => (12, true),        // Dominator Platinum DDR4 and DDR5, Dominator Titanium
        0x04 or 0x0B => (6, false),                // Vengeance RS, DDR4 and DDR5
        _ => (10, false),                          // Vengeance RGB Pro (SL), Vengeance RGB DDR5, Shugo
    };

    public static byte Crc8(ReadOnlySpan<byte> data)
    {
        byte crc = 0;
        foreach (byte value in data)
        {
            crc ^= value;
            for (int i = 0; i < 8; i++)
                crc = (byte)((crc & 0x80) != 0 ? (crc << 1) ^ 0x07 : crc << 1);
        }
        return crc;
    }

    /// <summary>The effect set on the stick: null, or what went wrong.</summary>
    public static string? Apply(Module module, Effect effect)
    {
        var data = new byte[20];
        data[0] = effect.Mode;
        data[1] = effect.Speed;
        data[2] = (byte)(effect.Random ? 0 : 1);
        data[3] = effect.Direction;
        data[4] = effect.A[0];
        data[5] = effect.A[1];
        data[6] = effect.A[2];
        data[7] = effect.Brightness;
        data[8] = effect.B[0];
        data[9] = effect.B[1];
        data[10] = effect.B[2];
        data[11] = effect.Brightness;
        try
        {
            using (module.Bus.Lock())
            {
                if (!Send(module, data, EffectBuffer))
                    return $"the memory at 0x{module.Address:X2} did not take the effect";
                if (effect.Mode != Effect.Static)
                    return null;
                // a still effect's colours are each light's own: the gradient along the stick
                var colours = new byte[module.Leds * 4];
                for (int i = 0; i < module.Leds; i++)
                {
                    int from = (module.Reversed ? module.Leds - 1 - i : i) * Effect.MaxLeds / module.Leds;
                    for (int c = 0; c < 3; c++)
                        colours[i * 4 + c] = (byte)(effect.Leds[from * 3 + c] * effect.Brightness / 255);
                    colours[i * 4 + 3] = 0xFF;
                }
                return Send(module, colours, ColourBuffer)
                    ? null : $"the memory at 0x{module.Address:X2} did not take the colours";
            }
        }
        catch (System.TimeoutException error)
        {
            return error.Message;
        }
    }

    static bool Send(Module module, byte[] data, byte buffer)
    {
        var (bus, address) = (module.Bus, module.Address);
        for (int attempt = 0; attempt < 2; attempt++)
        {
            bool sent = bus.WriteByte(address, ResetBuffer, 0) && bus.WriteByte(address, Start, 0);
            for (int i = 0; sent && i < data.Length; i++)
                sent = bus.WriteByte(address, SetData, data[i]);
            if (!sent || bus.ReadByte(address, Checksum) != Crc8(data))
                continue;
            if (!bus.WriteByte(address, ApplyBuffer, buffer))
                continue;
            for (int wait = 0; wait < 10; wait++)
            {
                int status = bus.ReadByte(address, Status);
                if (status >= 0 && (status & 0x08) == 0)
                    return true;
                Thread.Sleep(10);
            }
            return true;                            // applied; it only stayed busy a while
        }
        return false;
    }
}

/// <summary>Two stand-in Corsair Vengeance RGB DDR5 sticks, for tests: they answer as real ones do,
/// and each effect or colours applied is printed ("applied 58 1 <hex>").</summary>
public sealed class FakeBus : ISmbus
{
    sealed class Stick
    {
        public readonly List<byte> Buffer = [];
        public int Reading;
        public byte[] Info = new byte[32];
    }

    readonly Dictionary<byte, Stick> _sticks = [];
    public string Name => "stand-in SMBus";

    public FakeBus()
    {
        foreach (byte address in new byte[] { 0x58, 0x5A })
        {
            var stick = new Stick();
            stick.Info[0] = 0x1C;
            stick.Info[1] = 0x1B;
            stick.Info[2] = 0x00;
            stick.Info[3] = 0x07;                    // Vengeance RGB DDR5
            stick.Info[8] = 3;
            stick.Info[9] = 1;
            stick.Info[28] = 4;
            _sticks[address] = stick;
        }
    }

    public static Opened Open() => new([new FakeBus()], Status.Ready, "");

    public int ReadByte(byte address, byte command)
    {
        if (!_sticks.TryGetValue(address, out var stick))
            return -1;
        return command switch
        {
            0x43 => 0x1B,
            0x44 => 0x04,
            0x30 => 0,
            0x40 => stick.Reading < 32 ? stick.Info[stick.Reading++] : 0,
            0x42 => stick.Reading > 0 ? Corsair.Crc8(stick.Info) : Corsair.Crc8(stick.Buffer.ToArray()),
            _ => 0,
        };
    }

    public bool WriteByte(byte address, byte command, byte value)
    {
        if (!_sticks.TryGetValue(address, out var stick))
            return false;
        switch (command)
        {
            case 0x61:
                stick.Reading = 0;
                break;
            case 0x0B:
                stick.Buffer.Clear();
                stick.Reading = -1;
                break;
            case 0x20:
                stick.Buffer.Add(value);
                break;
            case 0x82:
                Console.WriteLine($"applied {address:X2} {value} {Convert.ToHexString(stick.Buffer.ToArray())}");
                Console.Out.Flush();
                break;
        }
        return true;
    }

    public IDisposable Lock() => new Nothing();

    sealed class Nothing : IDisposable
    {
        public void Dispose() { }
    }

    public void Dispose() { }
}

// --- the shared memory ----------------------------------------------------------------------

/// <summary>The two blocks of shared memory and the event.
///
/// The status (written here; little-endian), version 1:
///   0  uint32  magic, "KGLT"
///   4  uint32  layout version
///   8  uint32  sequence - odd while being written
///  12  int32   status (Status)
///  16  int64   when: ms since 1970, UTC
///  24  uint32  the last request set
///  28  uint32  the last request that failed
///  32  uint32  how many sticks were found (up to 8)
///  40  8 x 16  each stick: bus, address, product id (2), lights, protocol, firmware (ASCII, 10)
/// 168  char16[96]  what went wrong, NUL-ended
///
/// The request (written by Keyglow):
///   0  uint32  magic, "KGLA"
///   4  uint32  layout version
///   8  uint32  sequence - odd while being written
///  12  uint32  the request's number (anything new is set)
///  16  mode, speed, random, direction, brightness, colour A (3), colour B (3), (1 spare)
///  28  12 x 3  each light's colour, for the still effect
/// </summary>
public sealed unsafe class Blocks : IDisposable
{
    public const uint StatusMagic = 0x544C474B, AskMagic = 0x414C474B;
    public const int Size = 4096;
    // SYSTEM and administrators: everything; signed-in users: read the status, write the request,
    // set the event.
    const string StatusSddl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GR;;;AU)";
    const string AskSddl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;AU)";
    const string WantedSddl = "D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x00100002;;;AU)";

    readonly IntPtr _status, _ask, _wanted;
    readonly byte* _statusView, _askView;
    uint _sequence;

    public Blocks(string status, string ask, string wanted, bool forEveryone)
    {
        _status = Native.Create(forEveryone ? StatusSddl : null,
            sa => Native.CreateFileMappingW(new IntPtr(-1), sa, Native.PAGE_READWRITE, 0, Size, status));
        _ask = Native.Create(forEveryone ? AskSddl : null,
            sa => Native.CreateFileMappingW(new IntPtr(-1), sa, Native.PAGE_READWRITE, 0, Size, ask));
        _statusView = (byte*)Native.MapViewOfFile(_status, Native.FILE_MAP_WRITE, 0, 0, Size);
        _askView = (byte*)Native.MapViewOfFile(_ask, Native.FILE_MAP_WRITE, 0, 0, Size);
        if (_statusView == null || _askView == null)
            throw new Win32Exception();
        _wanted = Native.Create(forEveryone ? WantedSddl : null, sa => Native.CreateEventW(sa, false, false, wanted));
        _sequence = *(uint*)(_statusView + 8) & ~1u;
        *(uint*)_statusView = StatusMagic;
        *(uint*)(_statusView + 4) = 1;
    }

    public bool WaitWanted(int ms) => Native.WaitForSingleObject(_wanted, (uint)ms) == 0;

    public void Wake() => Native.SetEvent(_wanted);

    public void WriteStatus(Status status, IList<Module> modules, uint done, uint failed, string message)
    {
        byte* v = _statusView;
        Volatile.Write(ref *(uint*)(v + 8), ++_sequence);
        Thread.MemoryBarrier();
        *(int*)(v + 12) = (int)status;
        *(long*)(v + 16) = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        *(uint*)(v + 24) = done;
        *(uint*)(v + 28) = failed;
        int count = Math.Min(modules.Count, 8);
        *(uint*)(v + 32) = (uint)count;
        for (int i = 0; i < 8; i++)
        {
            byte* m = v + 40 + i * 16;
            for (int j = 0; j < 16; j++)
                m[j] = 0;
            if (i >= count)
                continue;
            var module = modules[i];
            m[0] = (byte)module.BusIndex;
            m[1] = module.Address;
            *(ushort*)(m + 2) = module.Pid;
            m[4] = (byte)module.Leds;
            m[5] = module.Protocol;
            for (int j = 0; j < Math.Min(module.Firmware.Length, 10); j++)
                m[6 + j] = (byte)module.Firmware[j];
        }
        char* words = (char*)(v + 168);
        int length = Math.Min(message.Length, 95);
        for (int i = 0; i < length; i++)
            words[i] = message[i];
        words[length] = '\0';
        Thread.MemoryBarrier();
        Volatile.Write(ref *(uint*)(v + 8), ++_sequence);
    }

    /// <summary>The request as it stands: its number and effect, or null if none was written
    /// (or it was mid-write each time it was looked at).</summary>
    public (uint, Effect)? ReadAsk()
    {
        byte* v = _askView;
        for (int attempt = 0; attempt < 50; attempt++)
        {
            uint before = Volatile.Read(ref *(uint*)(v + 8));
            if ((before & 1) != 0)
            {
                Thread.Sleep(1);
                continue;
            }
            Thread.MemoryBarrier();
            if (*(uint*)v != AskMagic || *(uint*)(v + 4) != 1)
                return null;
            uint number = *(uint*)(v + 12);
            var bytes = new ReadOnlySpan<byte>(v + 16, 12 + Effect.MaxLeds * 3).ToArray();
            Thread.MemoryBarrier();
            if (Volatile.Read(ref *(uint*)(v + 8)) != before)
                continue;
            if (number == 0)
                return null;
            var effect = new Effect(bytes[0], bytes[1], bytes[2] != 0, bytes[3], bytes[4], bytes[5..8], bytes[8..11],
                                    bytes[12..]);
            return (number, effect);
        }
        return null;
    }

    public void Dispose()
    {
        if (_statusView != null)
            Native.UnmapViewOfFile((IntPtr)_statusView);
        if (_askView != null)
            Native.UnmapViewOfFile((IntPtr)_askView);
        Native.CloseHandle(_status);
        Native.CloseHandle(_ask);
        Native.CloseHandle(_wanted);
    }
}

sealed class LightsService : ServiceBase
{
    Thread? _worker;
    Blocks? _blocks;
    volatile bool _stopping;

    public LightsService()
    {
        ServiceName = Program.ServiceName;
        CanStop = true;
        CanShutdown = true;
    }

    protected override void OnStart(string[] args)
    {
        _blocks = new Blocks(Program.StatusName, Program.AskName, Program.WantedName, forEveryone: true);
        var blocks = _blocks;
        _worker = new Thread(() =>
        {
            Loop.Run(blocks, PawnIoBus.OpenAll, Program.IdleMs, () => _stopping);
            if (!_stopping)
                Stop();                             // a minute without being asked
        }) { IsBackground = true, Name = "lights" };
        _worker.Start();
    }

    protected override void OnStop()
    {
        _stopping = true;
        _blocks?.Wake();
        if (_worker is not null && _worker != Thread.CurrentThread)
            _worker.Join(5000);
        _blocks?.Dispose();
        _blocks = null;
    }

    protected override void OnShutdown() => OnStop();
}

static class Native
{
    public const uint PAGE_READWRITE = 0x04;
    public const uint FILE_MAP_WRITE = 0x02;

    [StructLayout(LayoutKind.Sequential)]
    public struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        public int bInheritHandle;
    }

    /// <summary>A named object made with a security descriptor from SDDL (none: the default).</summary>
    public static IntPtr Create(string? sddl, Func<IntPtr, IntPtr> make)
    {
        IntPtr descriptor = IntPtr.Zero, attributes = IntPtr.Zero;
        try
        {
            if (sddl is not null)
            {
                if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out descriptor, IntPtr.Zero))
                    throw new Win32Exception();
                var sa = new SECURITY_ATTRIBUTES
                {
                    nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), lpSecurityDescriptor = descriptor,
                };
                attributes = Marshal.AllocHGlobal(sa.nLength);
                Marshal.StructureToPtr(sa, attributes, false);
            }
            IntPtr handle = make(attributes);
            if (handle == IntPtr.Zero)
                throw new Win32Exception();
            return handle;
        }
        finally
        {
            if (attributes != IntPtr.Zero)
                Marshal.FreeHGlobal(attributes);
            if (descriptor != IntPtr.Zero)
                LocalFree(descriptor);
        }
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string sddl, uint revision,
        out IntPtr descriptor, IntPtr size);

    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr memory);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateFileMappingW(IntPtr file, IntPtr attributes, uint protect, uint sizeHigh,
        uint sizeLow, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr MapViewOfFile(IntPtr mapping, uint access, uint offsetHigh, uint offsetLow, UIntPtr size);

    public static IntPtr MapViewOfFile(IntPtr mapping, uint access, uint offsetHigh, uint offsetLow, int size) =>
        MapViewOfFile(mapping, access, offsetHigh, offsetLow, (UIntPtr)size);

    [DllImport("kernel32.dll")]
    public static extern bool UnmapViewOfFile(IntPtr view);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateEventW(IntPtr attributes, bool manualReset, bool initialState, string name);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateMutexW(IntPtr attributes, bool initialOwner, string name);

    [DllImport("kernel32.dll")]
    public static extern bool ReleaseMutex(IntPtr handle);

    [DllImport("kernel32.dll")]
    public static extern bool SetEvent(IntPtr handle);

    [DllImport("kernel32.dll")]
    public static extern uint WaitForSingleObject(IntPtr handle, uint ms);

    [DllImport("kernel32.dll")]
    public static extern bool CloseHandle(IntPtr handle);
}
