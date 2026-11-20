using System;
using System.Runtime.InteropServices;

public static class RundownMediaPicker
{
    private const uint PickFolders = 0x20;
    private const uint ForceFileSystem = 0x40;
    private const uint AllowMultiSelect = 0x200;
    private const uint PathMustExist = 0x800;
    private const uint FileSystemPath = 0x80058000;
    private const int Cancelled = unchecked((int)0x800704C7);

    [ComImport]
    [Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    private class FileOpenDialog { }

    [ComImport]
    [Guid("D57C7288-D4AD-4768-BE02-9D969532D960")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileOpenDialog
    {
        // Keep the inherited Show and IFileDialog slots in their SDK order.
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, [MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 0)] FilterSpec[] filters);
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
        void AddPlace(IShellItem item, int position);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
        void Close(int result);
        void SetClientGuid(ref Guid id);
        void ClearClientData();
        void SetFilter(IntPtr filter);
        void GetResults(out IShellItemArray items);
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct FilterSpec
    {
        public FilterSpec(string name, string pattern) { Name = name; Pattern = pattern; }
        [MarshalAs(UnmanagedType.LPWStr)] public string Name;
        [MarshalAs(UnmanagedType.LPWStr)] public string Pattern;
    }

    [ComImport]
    [Guid("B63EA76D-1F85-456F-A19C-48159EFA858B")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItemArray
    {
        void BindToHandler(IntPtr context, ref Guid handler, ref Guid interfaceId, out IntPtr result);
        void GetPropertyStore(int flags, ref Guid interfaceId, out IntPtr store);
        void GetPropertyDescriptionList(IntPtr key, ref Guid interfaceId, out IntPtr description);
        void GetAttributes(int flags, uint mask, out uint attributes);
        void GetCount(out uint count);
        void GetItemAt(uint index, out IShellItem item);
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

    private static void SetInitialFolder(IFileOpenDialog dialog, string folder)
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

    private static void Configure(IFileOpenDialog dialog, string title, string initialFolder,
        string kind, bool multiple, string pattern)
    {
        bool folder = kind == "folder";
        uint options;
        dialog.GetOptions(out options);
        options |= ForceFileSystem | PathMustExist;
        if (folder) options |= PickFolders;
        if (multiple) options |= AllowMultiSelect;
        dialog.SetOptions(options);
        dialog.SetTitle(title);
        if (folder)
            dialog.SetOkButtonLabel("Select folder");
        else if (!String.IsNullOrEmpty(pattern))
            dialog.SetFileTypes(1, new[] { new FilterSpec(kind == "backup" ? "Rundown backups" : "Video files", pattern) });
        SetInitialFolder(dialog, initialFolder);
    }

    private static string ReadPath(IShellItem item)
    {
        try
        {
            IntPtr path;
            item.GetDisplayName(FileSystemPath, out path);
            try { return Marshal.PtrToStringUni(path); }
            finally { Marshal.FreeCoTaskMem(path); }
        }
        finally { Marshal.ReleaseComObject(item); }
    }

    public static string[] Show(string title, string initialFolder, string kind, bool multiple, string pattern)
    {
        var dialog = (IFileOpenDialog)new FileOpenDialog();
        try
        {
            Configure(dialog, title, initialFolder, kind, multiple, pattern);
            int result = dialog.Show(IntPtr.Zero);
            if (result == Cancelled)
                return new string[0];
            Marshal.ThrowExceptionForHR(result);

            IShellItemArray items;
            dialog.GetResults(out items);
            try
            {
                uint count;
                items.GetCount(out count);
                var paths = new string[count];
                for (uint index = 0; index < count; index++)
                {
                    IShellItem item;
                    items.GetItemAt(index, out item);
                    paths[index] = ReadPath(item);
                }
                return paths;
            }
            finally { Marshal.ReleaseComObject(items); }
        }
        finally { Marshal.ReleaseComObject(dialog); }
    }
}
