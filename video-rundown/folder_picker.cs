using System;
using System.Runtime.InteropServices;

public static class RundownFolderPicker
{
    private const uint PickFolders = 0x20;
    private const uint ForceFileSystem = 0x40;
    private const uint PathMustExist = 0x800;
    private const uint FileSystemPath = 0x80058000;
    private const int Cancelled = unchecked((int)0x800704C7);

    [ComImport]
    [Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    private class FileOpenDialog { }

    [ComImport]
    [Guid("42F85136-DB7E-439C-85F1-E4075D135FC8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileDialog
    {
        // Keep the inherited Show and IFileDialog slots in their SDK order.
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, IntPtr filters);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem item);
        void SetFolder(IShellItem item);
        void GetFolder(out IShellItem item);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName(out IntPtr name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
    }

    [ComImport]
    [Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler(IntPtr context, ref Guid handler, ref Guid interfaceId, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint displayNameType, out IntPtr path);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int SHCreateItemFromParsingName(string path, IntPtr bindingContext,
        ref Guid interfaceId, out IShellItem item);

    private static void SetInitialFolder(IFileDialog dialog, string folder)
    {
        if (String.IsNullOrEmpty(folder))
            return;

        IShellItem item;
        Guid interfaceId = typeof(IShellItem).GUID;
        if (SHCreateItemFromParsingName(folder, IntPtr.Zero, ref interfaceId, out item) < 0)
            return;

        try { dialog.SetFolder(item); }
        catch (COMException) { /* The folder may have disconnected before opening. */ }
        finally { Marshal.ReleaseComObject(item); }
    }

    public static string Show(string title, IntPtr owner, string initialFolder)
    {
        var dialog = (IFileDialog)new FileOpenDialog();
        try
        {
            uint options;
            dialog.GetOptions(out options);
            dialog.SetOptions(options | PickFolders | ForceFileSystem | PathMustExist);
            dialog.SetTitle(title);
            dialog.SetOkButtonLabel("Select folder");
            SetInitialFolder(dialog, initialFolder);
            int result = dialog.Show(owner);
            if (result == Cancelled)
                return null;
            Marshal.ThrowExceptionForHR(result);

            IShellItem item;
            dialog.GetResult(out item);
            try
            {
                IntPtr path;
                item.GetDisplayName(FileSystemPath, out path);
                try { return Marshal.PtrToStringUni(path); }
                finally { Marshal.FreeCoTaskMem(path); }
            }
            finally { Marshal.ReleaseComObject(item); }
        }
        finally { Marshal.ReleaseComObject(dialog); }
    }
}
