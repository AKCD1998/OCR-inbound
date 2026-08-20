using System.Linq;
using System.Windows;
namespace OcrInboundSpike {
  public partial class MainWindow : Window {
    public MainWindow() { InitializeComponent(); Lines.ItemsSource = Enumerable.Range(1, 120).Select(i => new { Sequence=i, Code=$"630{i:0000}", Description="ยาพาราเซตามอล 500 มก. กล่องทดสอบ", Unit="BOX", Quantity="12", Price="35.50", Total="426.00", Status="ต้องตรวจ" }); }
  }
}
